"""
hardware_io.py — Couche d'abstraction matérielle pour la passerelle Modbus/OPC-UA.

Centralise l'accès à tous les capteurs/actionneurs physiques du Raspberry Pi 4.
Chaque capteur/actionneur est isolé dans son propre try/except : une panne sur
l'un ne bloque jamais la lecture/écriture des autres (même logique que
test_capteurs.py, qui a confirmé les 8 composants fonctionnels sur ce brochage).

Avec simulate=True, aucun import matériel n'est fait : toutes les valeurs
restent à zéro. Ça permet de développer/tester modbus_hardware_slave.py et
gateway.py n'importe où (pas seulement sur le Pi branché).
"""
import logging
import threading
import time

log = logging.getLogger("hardware_io")

# --- Broches GPIO (confirmées par test_capteurs.py : 11/11 OK) ---
PIN_DHT11 = 4           # GPIO4  / broche physique 7
PIN_PIR = 17            # GPIO17 / broche physique 11
PIN_SERVO = 18          # GPIO18 / broche physique 12
PINS_RELAIS = [5, 6, 13, 19]        # broches physiques 29, 31, 33, 35
PINS_STEPPER = [26, 16, 20, 21]     # broches physiques 37, 36, 38, 40
PIN_HCSR04_TRIG = 23    # broche physique 16
PIN_HCSR04_ECHO = 24    # broche physique 18 (via pont diviseur de tension)

I2C_ADDR_LCD_CANDIDATES = (0x27, 0x3F)


class HardwareIO:
    """Accès centralisé et thread-safe aux capteurs/actionneurs physiques."""

    def __init__(self, simulate=False):
        self.simulate = simulate
        self._lock = threading.Lock()

        # Dernières valeurs connues — toujours disponibles, même juste après
        # une erreur de lecture passagère (on ne remet jamais à zéro sur erreur).
        self.temperature_c = 0.0
        self.humidity_pct = 0.0
        self.distance_cm = 0.0
        self.distance_valide = False   # True dès la première vraie mesure HC-SR04 reçue
        self.mq2_voltage = 0.0
        self.pot_voltage = 0.0
        self.pir_motion = False

        # Messages imposés par le scénario automatique (ex: alerte de présence,
        # objet qui approche), par source, tant qu'ils ne sont pas effacés — voir
        # set_lcd_message()/refresh_lcd().
        self._lcd_messages = {}

        self._dht = None
        self._ads_chan0 = None
        self._ads_chan1 = None
        self._pir = None
        self._servo = None
        self._relais = []
        self._lcd = None
        self._gpio = None

        if not self.simulate:
            self._init_hardware()
        else:
            log.info("HardwareIO en mode simulation — aucun GPIO/I2C réel utilisé")

    # ------------------------------------------------------------------
    # Initialisation (une seule fois, au démarrage)
    # ------------------------------------------------------------------
    def _init_hardware(self):
        # Relais en tout premier, avant tout autre import/init (DHT11, I2C,
        # pigpio...) qui peut prendre une à deux secondes. Tant que la broche
        # n'est pas explicitement revendiquée en sortie, elle reste flottante
        # (état par défaut du GPIO) et peut être lue comme "actif" par le
        # module de relais pendant cette fenêtre — d'où les LED qui semblent
        # s'allumer brièvement au lancement. En la configurant tout de suite
        # (initial_value=False -> HIGH -> relais/LED éteints puisque
        # active_high=False), cette fenêtre est réduite au strict minimum.
        try:
            from gpiozero import OutputDevice

            self._relais = [
                OutputDevice(p, active_high=False, initial_value=False) for p in PINS_RELAIS
            ]
        except Exception as e:
            log.warning("Relais indisponibles à l'init : %s", e)

        try:
            # pigpio génère le signal PWM de façon matérielle/précise (au lieu
            # du PWM logiciel par défaut de gpiozero), ce qui évite les petits
            # tremblements du servo quand il est censé rester fixe. Nécessite
            # que le démon pigpiod tourne sur le Pi (sudo systemctl start
            # pigpiod). Si pigpio n'est pas disponible, on retombe simplement
            # sur le PWM logiciel habituel (fonctionnel, juste moins stable).
            from gpiozero import Device
            from gpiozero.pins.pigpio import PiGPIOFactory

            Device.pin_factory = PiGPIOFactory()
            log.info("pigpio activé pour gpiozero (PWM matériel, servo stable)")
        except Exception as e:
            log.warning(
                "pigpio indisponible, PWM logiciel utilisé (le servo peut trembler légèrement) : %s",
                e,
            )

        try:
            import board
            import adafruit_dht

            self._dht = adafruit_dht.DHT11(board.D4)
        except Exception as e:
            log.warning("DHT11 indisponible à l'init : %s", e)

        try:
            import board
            import busio
            import adafruit_ads1x15.ads1115 as ADS
            from adafruit_ads1x15.analog_in import AnalogIn

            i2c = busio.I2C(board.SCL, board.SDA)
            ads = ADS.ADS1115(i2c)
            # Les canaux se passent en numéro simple (0-3) sur les versions
            # récentes de la librairie — ADS.P0/ADS.P1 n'existent plus.
            self._ads_chan0 = AnalogIn(ads, 0)   # MQ-2
            self._ads_chan1 = AnalogIn(ads, 1)   # potentiomètre
        except Exception as e:
            log.warning("ADS1115 indisponible à l'init : %s", e)

        try:
            from RPLCD.i2c import CharLCD

            for addr in I2C_ADDR_LCD_CANDIDATES:
                try:
                    self._lcd = CharLCD("PCF8574", addr, cols=16, rows=2)
                    break
                except Exception:
                    self._lcd = None
            if self._lcd is None:
                log.warning("LCD indisponible à l'init (aucune adresse n'a répondu)")
        except Exception as e:
            log.warning("LCD indisponible à l'init : %s", e)

        try:
            from gpiozero import MotionSensor

            self._pir = MotionSensor(PIN_PIR)
        except Exception as e:
            log.warning("PIR indisponible à l'init : %s", e)

        try:
            from gpiozero import Servo

            self._servo = Servo(PIN_SERVO)
        except Exception as e:
            log.warning("Servo indisponible à l'init : %s", e)

        try:
            import RPi.GPIO as GPIO

            self._gpio = GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            for p in PINS_STEPPER:
                GPIO.setup(p, GPIO.OUT)
            GPIO.setup(PIN_HCSR04_TRIG, GPIO.OUT)
            GPIO.setup(PIN_HCSR04_ECHO, GPIO.IN)
            GPIO.output(PIN_HCSR04_TRIG, False)
        except Exception as e:
            log.warning("RPi.GPIO (pas-à-pas / HC-SR04) indisponible à l'init : %s", e)

    # ------------------------------------------------------------------
    # Lecture des capteurs
    # ------------------------------------------------------------------
    def read_dht11(self):
        if self._dht is None:
            return
        try:
            t = self._dht.temperature
            h = self._dht.humidity
            if t is not None and h is not None:
                with self._lock:
                    self.temperature_c = float(t)
                    self.humidity_pct = float(h)
        except RuntimeError as e:
            # Le DHT11 rate une lecture de temps en temps, c'est normal.
            log.debug("DHT11 lecture ratée (normal occasionnellement) : %s", e)
        except Exception as e:
            log.warning("DHT11 erreur : %s", e)

    def read_ads1115(self):
        if self._ads_chan0 is None or self._ads_chan1 is None:
            return
        try:
            v0 = float(self._ads_chan0.voltage)
            v1 = float(self._ads_chan1.voltage)
            with self._lock:
                self.mq2_voltage = v0
                self.pot_voltage = v1
        except Exception as e:
            log.warning("ADS1115 erreur : %s", e)

    def read_pir(self):
        if self._pir is None:
            return
        try:
            motion = bool(self._pir.motion_detected)
            with self._lock:
                self.pir_motion = motion
        except Exception as e:
            log.warning("PIR erreur : %s", e)

    def read_hcsr04(self):
        if self._gpio is None:
            return
        GPIO = self._gpio
        try:
            GPIO.output(PIN_HCSR04_TRIG, True)
            time.sleep(0.00001)
            GPIO.output(PIN_HCSR04_TRIG, False)

            start = None
            stop = None

            timeout = time.time() + 0.05
            while GPIO.input(PIN_HCSR04_ECHO) == 0 and time.time() < timeout:
                start = time.time()

            timeout = time.time() + 0.05
            while GPIO.input(PIN_HCSR04_ECHO) == 1 and time.time() < timeout:
                stop = time.time()

            if start is not None and stop is not None:
                distance = round((stop - start) * 17150, 1)
                if 2.0 <= distance <= 400.0:   # plage utile du HC-SR04
                    with self._lock:
                        self.distance_cm = distance
                        self.distance_valide = True
        except Exception as e:
            log.warning("HC-SR04 erreur : %s", e)

    def read_all_sensors(self):
        """Appelé périodiquement par le thread de scrutation des capteurs."""
        self.read_dht11()
        self.read_ads1115()
        self.read_pir()
        self.read_hcsr04()

    # ------------------------------------------------------------------
    # Snapshot thread-safe, consommé par le serveur Modbus
    # ------------------------------------------------------------------
    def snapshot(self):
        with self._lock:
            return {
                "temperature_c": self.temperature_c,
                "humidity_pct": self.humidity_pct,
                "distance_cm": self.distance_cm,
                "distance_valide": self.distance_valide,
                "mq2_voltage": self.mq2_voltage,
                "pot_voltage": self.pot_voltage,
                "pir_motion": self.pir_motion,
            }

    # ------------------------------------------------------------------
    # Commande des actionneurs
    # ------------------------------------------------------------------
    def set_relais(self, index, state):
        if not (0 <= index < len(self._relais)):
            return
        try:
            if state:
                self._relais[index].on()
            else:
                self._relais[index].off()
        except Exception as e:
            log.warning("Relais %d erreur : %s", index, e)

    def set_servo_angle(self, angle_deg):
        if self._servo is None:
            return
        try:
            angle_deg = max(0, min(180, angle_deg))
            value = (angle_deg / 90.0) - 1.0   # 0° -> -1.0, 90° -> 0.0, 180° -> 1.0
            self._servo.value = value
        except Exception as e:
            log.warning("Servo erreur : %s", e)

    def run_stepper_steps(self, direction, steps):
        """direction : 0 = horaire, 1 = anti-horaire. steps : nombre de pas (positif)."""
        if self._gpio is None or steps <= 0:
            return
        GPIO = self._gpio
        sequence = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        if direction == 1:
            sequence = list(reversed(sequence))
        try:
            for _ in range(int(steps)):
                for step in sequence:
                    for p, val in zip(PINS_STEPPER, step):
                        GPIO.output(p, val)
                    time.sleep(0.003)
        except Exception as e:
            log.warning("Pas-à-pas erreur : %s", e)

    def run_stepper_for_duration(self, direction, duration_s):
        """Comme run_stepper_steps, mais tourne en continu pendant duration_s secondes
        plutôt qu'un nombre de pas fixe — utilisé par le scénario automatique."""
        if self._gpio is None or duration_s <= 0:
            return
        GPIO = self._gpio
        sequence = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        if direction == 1:
            sequence = list(reversed(sequence))
        fin = time.time() + duration_s
        try:
            while time.time() < fin:
                for step in sequence:
                    for p, val in zip(PINS_STEPPER, step):
                        GPIO.output(p, val)
                    time.sleep(0.003)
        except Exception as e:
            log.warning("Pas-à-pas erreur : %s", e)

    def update_lcd(self, line1, line2=""):
        if self._lcd is None:
            return
        try:
            self._lcd.clear()
            self._lcd.write_string(line1[:16])
            if line2:
                self._lcd.cursor_pos = (1, 0)
                self._lcd.write_string(line2[:16])
        except Exception as e:
            log.warning("LCD erreur : %s", e)

    def set_lcd_message(self, source, message):
        """Impose un message sur la ligne du bas de l'écran, associé à une source
        (ex: "pir", "hcsr04"), jusqu'à ce qu'il soit effacé par clear_lcd_message(source).
        Plusieurs sources peuvent être actives en même temps (ex: présence ET objet qui
        approche) — une seule s'affiche à la fois, par ordre de priorité (voir refresh_lcd).
        La ligne du haut (température/humidité) reste toujours affichée, quoi qu'il arrive."""
        with self._lock:
            self._lcd_messages[source] = message

    def clear_lcd_message(self, source):
        """Retire le message imposé par cette source. La ligne du bas revient à l'affichage
        normal (distance) uniquement si plus aucune source n'a de message actif."""
        with self._lock:
            self._lcd_messages.pop(source, None)

    # Ordre de priorité quand plusieurs messages sont actifs en même temps.
    _PRIORITE_MESSAGES_LCD = ("pir", "hcsr04")

    def refresh_lcd(self):
        """Ligne du haut : toujours température/humidité. Ligne du bas : le message du
        scénario automatique le plus prioritaire s'il y en a un, sinon la distance. Appelé
        périodiquement par sensor_loop à la place d'écrire directement sur l'écran, pour
        éviter que deux threads ne se marchent dessus."""
        with self._lock:
            messages = dict(self._lcd_messages)
            temp = self.temperature_c
            hum = self.humidity_pct
            dist = self.distance_cm
        ligne1 = f"T{temp:.1f}C H{hum:.0f}%"
        ligne2 = None
        for source in self._PRIORITE_MESSAGES_LCD:
            if source in messages:
                ligne2 = messages[source]
                break
        if ligne2 is None and messages:
            ligne2 = next(iter(messages.values()))
        if ligne2 is None:
            ligne2 = f"D{dist:.0f}cm"
        self.update_lcd(ligne1, ligne2)

    # ------------------------------------------------------------------
    def close(self):
        try:
            # Efface l'écran à l'arrêt du programme, plutôt que de laisser le dernier
            # contenu affiché indéfiniment (un écran I2C garde son affichage tant qu'il
            # est alimenté, même après la fin du script — ce n'est pas automatique).
            if self._lcd:
                self._lcd.clear()
        except Exception:
            pass
        try:
            if self._dht:
                self._dht.exit()
        except Exception:
            pass
        try:
            if self._pir:
                self._pir.close()
        except Exception:
            pass
        try:
            if self._servo:
                self._servo.close()
        except Exception:
            pass
        try:
            for r in self._relais:
                r.close()
        except Exception:
            pass
        try:
            if self._gpio:
                self._gpio.cleanup()
        except Exception:
            pass

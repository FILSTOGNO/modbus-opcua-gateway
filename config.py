"""Configuration centrale — Passerelle Modbus TCP -> OPC-UA (matériel réel)."""

# --- Serveur Modbus TCP (tourne sur le Raspberry Pi, lit le matériel réel) ---
MODBUS_HOST = "0.0.0.0"
MODBUS_PORT = 5020          # > 1024 : pas besoin de lancer le script en root
MODBUS_SLAVE_UNIT = 1

# --- Client Modbus utilisé par la passerelle (gateway.py) ---
# Si gateway.py tourne sur le même Raspberry Pi que le slave : "localhost".
# Si gateway.py tourne sur une autre machine du réseau : mets l'adresse IP du Pi.
MODBUS_CLIENT_HOST = "localhost"
MODBUS_CLIENT_PORT = MODBUS_PORT

# --- Serveur OPC-UA exposé par la passerelle ---
OPCUA_ENDPOINT = "opc.tcp://0.0.0.0:4840/gateway/"
OPCUA_NAMESPACE = "http://passerelle-modbus-opcua.local"

# --- Cadences ---
SENSOR_POLL_INTERVAL_S = 1.0       # fréquence de lecture des capteurs -> registres Modbus
ACTUATOR_POLL_INTERVAL_S = 0.3     # fréquence de surveillance des commandes -> GPIO
GATEWAY_POLL_INTERVAL_S = 1.0      # fréquence de la passerelle Modbus <-> OPC-UA
LCD_REFRESH_INTERVAL_S = 3.0       # fréquence de rafraîchissement de l'écran local

# --- Carte des registres Modbus ---
# (table complète et explication dans README.md)

# Discrete Inputs — lecture seule, 1 bit
DI_PIR = 0

# Input Registers — lecture seule, 16 bits, valeurs mises à l'échelle (xN pour éviter les flottants)
IR_TEMPERATURE = 0   # °C x10   (ex: 161 -> 16.1 °C)
IR_HUMIDITY = 1      # %  x10   (ex: 650 -> 65.0 %)
IR_DISTANCE = 2      # cm x10   (ex: 574 -> 57.4 cm)
IR_MQ2_MV = 3        # mV       (tension brute ADS1115 A0)
IR_POT_MV = 4        # mV       (tension brute ADS1115 A1)

# Coils — lecture/écriture, 1 bit
COIL_RELAIS_BASE = 0   # 4 relais consécutifs : adresses 0, 1, 2, 3

# Holding Registers — lecture/écriture, 16 bits
HR_SERVO_ANGLE = 0         # consigne servo, 0-180°
HR_STEPPER_DIRECTION = 1   # 0 = horaire, 1 = anti-horaire
HR_STEPPER_STEPS = 2       # nombre de pas à exécuter ; remis à 0 par le slave une fois fait

N_RELAIS = 4

# --- Scénario automatique (réactions capteurs -> actionneurs, sans commande externe) ---
AUTOMATION_POLL_INTERVAL_S = 0.3        # fréquence de surveillance des capteurs pour le scénario

AUTOMATION_LED_RELAIS_INDEX = 0         # quel relais sert de "LED" de présence (0 = Relais1)

PIR_DELAI_GRACE_DEMARRAGE_S = 2.0       # ignore toute détection PIR pendant les X premières
                                         # secondes après le lancement du script (évite une
                                         # fausse détection due à la prise en main de la broche
                                         # par gpiozero, même si le capteur physique est déjà
                                         # stable depuis longtemps)

HCSR04_SEUIL_APPROCHE_CM = 4.0          # en dessous de cette distance : "objet qui approche"
                                         # (le capteur filtre lui-même tout en dessous de 2cm
                                         # comme non fiable, donc 4cm reste réellement atteignable)
SERVO_ANGLE_REPOS = 0                   # position de repos du servo
SERVO_ANGLE_ALERTE = 180                # position quand un objet approche — amplitude maximale
                                         # (180°, le plus grand mouvement possible pour un servo
                                         # à position ; un vrai tour de 360° continu n'est physique-
                                         # ment possible qu'avec le pas-à-pas, pas un servo à position)

STEPPER_DELAI_APRES_DISPARITION_S = 5.0  # délai avant de lancer le pas-à-pas après la disparition de l'objet
STEPPER_DUREE_ROTATION_S = 10.0          # durée de rotation continue du pas-à-pas
STEPPER_PAUSE_S = 3.0                    # pause après la rotation, avant de considérer la séquence terminée
STEPPER_DIRECTION_AUTOMATIQUE = 0        # 0 = horaire, 1 = anti-horaire

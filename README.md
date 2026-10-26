# Passerelle Modbus TCP → OPC-UA — matériel réel (Raspberry Pi 4)

Ce dossier remplace la version "simulateur" du projet : les valeurs publiées
via OPC-UA viennent maintenant des vrais capteurs branchés sur le Raspberry
Pi 4, et les commandes reçues côté OPC-UA pilotent réellement les
actionneurs (relais, servo, moteur pas-à-pas).

## Architecture

```
 Capteurs/actionneurs physiques (GPIO, I2C)
              │
              ▼
     hardware_io.py          <- lit/écrit le matériel, isole chaque panne
              │
              ▼
 modbus_hardware_slave.py    <- serveur Modbus TCP (port 5020)
              │  Modbus TCP
              ▼
        gateway.py           <- client Modbus + serveur OPC-UA (port 4840)
              │  OPC-UA
              ▼
   n'importe quel client OPC-UA (test_opcua_client.py, UaExpert, ...)
```

`modbus_hardware_slave.py` tourne sur le Raspberry Pi (c'est lui qui touche
le GPIO/I2C réel). `gateway.py` peut tourner sur le même Pi ou sur une autre
machine du réseau (il suffit de changer `MODBUS_CLIENT_HOST` dans
`config.py`).

## Carte des registres Modbus

| Type               | Adresse | Nom                      | Lecture/Écriture | Échelle / valeurs            |
|---------------------|---------|---------------------------|-------------------|-------------------------------|
| Discrete Input      | 0       | PIR — présence            | Lecture seule     | 0 = rien, 1 = mouvement       |
| Input Register      | 0       | Température (DHT11)       | Lecture seule     | °C × 10                       |
| Input Register      | 1       | Humidité (DHT11)          | Lecture seule     | % × 10                        |
| Input Register      | 2       | Distance (HC-SR04)        | Lecture seule     | cm × 10                       |
| Input Register      | 3       | Tension MQ-2 (ADS1115 A0) | Lecture seule     | mV                             |
| Input Register      | 4       | Tension potentiomètre (A1)| Lecture seule     | mV                             |
| Coil                | 0–3     | Relais 1 à 4              | Lecture/Écriture  | 0 = ouvert, 1 = fermé          |
| Holding Register    | 0       | Consigne servo             | Lecture/Écriture  | degrés, 0–180                 |
| Holding Register    | 1       | Direction pas-à-pas         | Lecture/Écriture  | 0 = horaire, 1 = anti-horaire  |
| Holding Register    | 2       | Pas à exécuter              | Lecture/Écriture  | nombre de pas (auto-remis à 0)|

Les valeurs analogiques/physiques sont mises à l'échelle (×10 ou en mV) pour
rester dans un registre 16 bits sans perdre la décimale utile — `gateway.py`
les redivise avant de les republier en flottant côté OPC-UA.

## Installation sur le Raspberry Pi

```bash
cd ~/Projets/Capteur_Act   # ou l'emplacement de ton choix
pip install --break-system-packages -r requirements.txt
sudo raspi-config nonint do_i2c 0   # si pas déjà fait
```

## Lancement

Dans deux terminaux séparés (ou avec `tmux`/`screen`, ou en service
`systemd` plus tard) :

```bash
# Terminal 1 — sur le Raspberry Pi, lit/pilote le vrai matériel
python3 modbus_hardware_slave.py

# Terminal 2 — la passerelle (peut tourner sur le Pi ou ailleurs)
python3 gateway.py
```

Pour vérifier que tout remonte bien côté OPC-UA :

```bash
python3 test_opcua_client.py                   # affiche les capteurs en continu
python3 test_opcua_client.py --relais 1 --etat on   # active le relais 1
python3 test_opcua_client.py --servo 90              # positionne le servo à 90°
```

## Mode simulation (sans matériel, pour développer/tester ailleurs que sur le Pi)

```bash
python3 modbus_hardware_slave.py --simulate
```

Dans ce mode, aucun GPIO/I2C n'est touché — les capteurs restent à 0 et les
commandes d'actionneurs n'ont aucun effet physique. Ça permet de tester toute
la chaîne Modbus ↔ OPC-UA (lecture, écriture, va-et-vient des commandes)
sans être branché au Pi. C'est ainsi que cette version du code a été vérifiée
de bout en bout avant d'être déployée sur le matériel réel.

## Notes de conception

- **Résilience par capteur** : chaque capteur/actionneur est initialisé et
  lu dans son propre `try/except` (voir `hardware_io.py`). Si un capteur
  tombe en panne ou se débranche, les autres continuent de fonctionner — le
  registre correspondant garde simplement sa dernière valeur connue.
- **Pas-à-pas en registre "commande"** : plutôt que de suivre une position
  absolue (ce qui demanderait un encodeur), le pas-à-pas se pilote par un
  registre "nombre de pas à exécuter" que le slave remet à 0 une fois le
  mouvement effectué — un pattern Modbus classique pour les commandes
  ponctuelles.
- **Ordre d'exécution dans la boucle de la passerelle** : `gateway.py`
  pousse toujours les commandes OPC-UA vers Modbus *avant* de relire l'état
  Modbus pour rafraîchir l'OPC-UA. Dans l'autre ordre, une commande écrite
  par un client OPC-UA entre deux cycles de la passerelle serait écrasée par
  la relecture avant même d'avoir été transmise au Modbus.
- **Brochage** : toutes les broches utilisées dans `hardware_io.py`
  correspondent au câblage confirmé fonctionnel par `test_capteurs.py`
  (11/11 tests OK).

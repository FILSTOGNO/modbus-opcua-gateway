#!/usr/bin/env python3
"""
test_pir_standalone.py — Test isolé du capteur PIR, sans Modbus/OPC-UA/LCD.

Affiche l'état du PIR en continu, pour vérifier que le capteur détecte bien
un mouvement, indépendamment du reste de la passerelle.

Usage :
    python3 test_pir_standalone.py
"""
import time

from gpiozero import MotionSensor

PIN_PIR = 17  # même broche que dans hardware_io.py

pir = MotionSensor(PIN_PIR)

print("Capteur PIR initialisé sur GPIO%d." % PIN_PIR)
print("Agite la main devant le capteur (Ctrl+C pour arrêter).")
print("Si le module vient d'être mis sous tension, laisse-le ~30-60s pour se stabiliser.\n")

dernier_etat = None
try:
    while True:
        etat = pir.motion_detected
        if etat != dernier_etat:
            horodatage = time.strftime("%H:%M:%S")
            print(f"[{horodatage}] {'MOUVEMENT DETECTE' if etat else 'plus de mouvement'}")
            dernier_etat = etat
        time.sleep(0.1)
except KeyboardInterrupt:
    print("\nArrêt.")

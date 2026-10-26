#!/usr/bin/env python3
"""
test_opcua_client.py — Client OPC-UA de vérification.

Se connecte au serveur OPC-UA exposé par gateway.py, affiche toutes les
valeurs des capteurs en continu, et permet de tester l'écriture d'une
commande (relais, servo) depuis la ligne de commande.

Usage :
    python3 test_opcua_client.py                      # lecture continue
    python3 test_opcua_client.py --relais 1 on         # active le relais 1
    python3 test_opcua_client.py --relais 1 off        # désactive le relais 1
    python3 test_opcua_client.py --servo 90             # positionne le servo à 90°
"""
import argparse
import time

from opcua import Client

import config


def main():
    parser = argparse.ArgumentParser(description="Client de test OPC-UA pour la passerelle")
    parser.add_argument("--relais", type=int, choices=[1, 2, 3, 4], help="numéro de relais (1-4)")
    parser.add_argument("--etat", choices=["on", "off"], help="état à appliquer au relais")
    parser.add_argument("--servo", type=int, help="angle du servo en degrés (0-180)")
    parser.add_argument(
        "--endpoint",
        default=config.OPCUA_ENDPOINT.replace("0.0.0.0", "localhost"),
        help="endpoint OPC-UA à joindre",
    )
    args = parser.parse_args()

    client = Client(args.endpoint)
    client.connect()
    try:
        idx = client.get_namespace_index(config.OPCUA_NAMESPACE)
        objects = client.get_objects_node()
        passerelle = objects.get_child([f"{idx}:PasserelleModbus"])
        capteurs = passerelle.get_child([f"{idx}:Capteurs"])
        actionneurs = passerelle.get_child([f"{idx}:Actionneurs"])

        if args.relais and args.etat:
            node = actionneurs.get_child([f"{idx}:Relais{args.relais}"])
            node.set_value(args.etat == "on")
            print(f"Relais {args.relais} -> {args.etat}")
            return

        if args.servo is not None:
            node = actionneurs.get_child([f"{idx}:ServoAngleDeg"])
            node.set_value(args.servo)
            print(f"Servo -> {args.servo}°")
            return

        # Lecture continue de tous les capteurs
        noms = ["TemperatureC", "HumiditePct", "DistanceCm", "MQ2Voltage", "PotentiometreVoltage", "PIRMotion"]
        print("Lecture continue (Ctrl+C pour arrêter) :\n")
        while True:
            valeurs = []
            for nom in noms:
                node = capteurs.get_child([f"{idx}:{nom}"])
                valeurs.append(f"{nom}={node.get_value()}")
            print("  ".join(valeurs))
            time.sleep(1.0)

    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()

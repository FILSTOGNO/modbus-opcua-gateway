#!/usr/bin/env python3
"""
gateway.py — Passerelle Modbus TCP -> OPC-UA.

Se connecte en client Modbus TCP au serveur matériel (modbus_hardware_slave.py),
republie les mêmes valeurs comme variables OPC-UA, et répercute les écritures
OPC-UA (relais, servo, pas-à-pas) vers le serveur Modbus, qui pilote le GPIO réel.
"""
import logging
import time

from opcua import Server
from pymodbus.client import ModbusTcpClient

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("gateway")


class Gateway:
    def __init__(self):
        self.client = ModbusTcpClient(config.MODBUS_CLIENT_HOST, port=config.MODBUS_CLIENT_PORT)
        self.server = Server()
        self._nodes = {}
        self._running = False
        self._writing_back = False   # évite de renvoyer vers Modbus ce qu'on vient d'y lire
        # Dernière valeur effectivement écrite sur Modbus par la passerelle, pour ne pousser
        # une commande que si l'OPC-UA a vraiment changé (sinon on écraserait en boucle une
        # valeur posée directement côté Modbus, ex: par le scénario automatique du Pi).
        self._last_pushed_relais = [None] * config.N_RELAIS
        self._last_pushed_servo_angle = None

    # ------------------------------------------------------------------
    def setup_opcua(self):
        self.server.set_endpoint(config.OPCUA_ENDPOINT)
        idx = self.server.register_namespace(config.OPCUA_NAMESPACE)
        objects = self.server.get_objects_node()
        passerelle = objects.add_object(idx, "PasserelleModbus")

        capteurs = passerelle.add_object(idx, "Capteurs")
        self._nodes["temperature"] = capteurs.add_variable(idx, "TemperatureC", 0.0)
        self._nodes["humidity"] = capteurs.add_variable(idx, "HumiditePct", 0.0)
        self._nodes["distance"] = capteurs.add_variable(idx, "DistanceCm", 0.0)
        self._nodes["mq2"] = capteurs.add_variable(idx, "MQ2Voltage", 0.0)
        self._nodes["pot"] = capteurs.add_variable(idx, "PotentiometreVoltage", 0.0)
        self._nodes["pir"] = capteurs.add_variable(idx, "PIRMotion", False)

        actionneurs = passerelle.add_object(idx, "Actionneurs")
        self._nodes["relais"] = []
        for i in range(config.N_RELAIS):
            node = actionneurs.add_variable(idx, f"Relais{i + 1}", False)
            node.set_writable()
            self._nodes["relais"].append(node)

        self._nodes["servo_angle"] = actionneurs.add_variable(idx, "ServoAngleDeg", 0)
        self._nodes["servo_angle"].set_writable()

        self._nodes["stepper_direction"] = actionneurs.add_variable(idx, "PasAPasDirection", 0)
        self._nodes["stepper_direction"].set_writable()

        self._nodes["stepper_steps"] = actionneurs.add_variable(idx, "PasAPasNombreDePas", 0)
        self._nodes["stepper_steps"].set_writable()

    # ------------------------------------------------------------------
    def poll_modbus_to_opcua(self):
        """Lit les capteurs + l'état des relais côté Modbus, met à jour l'OPC-UA."""
        ir = self.client.read_input_registers(
            config.IR_TEMPERATURE, count=5, slave=config.MODBUS_SLAVE_UNIT
        )
        di = self.client.read_discrete_inputs(
            config.DI_PIR, count=1, slave=config.MODBUS_SLAVE_UNIT
        )
        co = self.client.read_coils(
            config.COIL_RELAIS_BASE, count=config.N_RELAIS, slave=config.MODBUS_SLAVE_UNIT
        )
        hr = self.client.read_holding_registers(
            config.HR_SERVO_ANGLE, count=1, slave=config.MODBUS_SLAVE_UNIT
        )

        if not ir.isError():
            regs = ir.registers
            self._nodes["temperature"].set_value(regs[0] / 10.0)
            self._nodes["humidity"].set_value(regs[1] / 10.0)
            self._nodes["distance"].set_value(regs[2] / 10.0)
            self._nodes["mq2"].set_value(regs[3] / 1000.0)
            self._nodes["pot"].set_value(regs[4] / 1000.0)
        else:
            log.warning("Lecture Modbus (input registers) échouée : %s", ir)

        if not di.isError():
            self._nodes["pir"].set_value(bool(di.bits[0]))
        else:
            log.warning("Lecture Modbus (discrete inputs) échouée : %s", di)

        if not co.isError():
            self._writing_back = True
            for i, bit in enumerate(co.bits[: config.N_RELAIS]):
                state = bool(bit)
                self._nodes["relais"][i].set_value(state)
                self._last_pushed_relais[i] = state   # déjà synchro, pas besoin de repousser
            self._writing_back = False
        else:
            log.warning("Lecture Modbus (coils) échouée : %s", co)

        if not hr.isError():
            angle = hr.registers[0]
            self._writing_back = True
            self._nodes["servo_angle"].set_value(angle)
            self._writing_back = False
            self._last_pushed_servo_angle = angle   # déjà synchro, pas besoin de repousser
        else:
            log.warning("Lecture Modbus (servo) échouée : %s", hr)

    def push_opcua_commands_to_modbus(self):
        """Répercute les commandes écrites côté OPC-UA (relais, servo, pas-à-pas) vers Modbus."""
        if self._writing_back:
            return

        for i, node in enumerate(self._nodes["relais"]):
            state = bool(node.get_value())
            if state == self._last_pushed_relais[i]:
                continue   # rien de nouveau côté OPC-UA pour ce relais : on ne réécrit pas
            result = self.client.write_coil(
                config.COIL_RELAIS_BASE + i, state, slave=config.MODBUS_SLAVE_UNIT
            )
            if result.isError():
                log.warning("Écriture Modbus relais %d (coil %d=%s) échouée : %s", i + 1, config.COIL_RELAIS_BASE + i, state, result)
            else:
                self._last_pushed_relais[i] = state

        angle = int(self._nodes["servo_angle"].get_value())
        if angle != self._last_pushed_servo_angle:
            result = self.client.write_register(config.HR_SERVO_ANGLE, angle, slave=config.MODBUS_SLAVE_UNIT)
            if result.isError():
                log.warning("Écriture Modbus servo (HR%d=%d) échouée : %s", config.HR_SERVO_ANGLE, angle, result)
            else:
                self._last_pushed_servo_angle = angle

        steps = int(self._nodes["stepper_steps"].get_value())
        if steps:
            direction = int(self._nodes["stepper_direction"].get_value())
            self.client.write_register(
                config.HR_STEPPER_DIRECTION, direction, slave=config.MODBUS_SLAVE_UNIT
            )
            self.client.write_register(
                config.HR_STEPPER_STEPS, steps, slave=config.MODBUS_SLAVE_UNIT
            )
            self._nodes["stepper_steps"].set_value(0)

    # ------------------------------------------------------------------
    def run(self):
        self.setup_opcua()
        self.client.connect()
        self.server.start()
        self._running = True
        log.info("Serveur OPC-UA démarré sur %s", config.OPCUA_ENDPOINT)
        log.info(
            "Connecté au serveur Modbus %s:%s", config.MODBUS_CLIENT_HOST, config.MODBUS_CLIENT_PORT
        )
        try:
            while self._running:
                # Important : on pousse d'abord les commandes OPC-UA vers Modbus,
                # puis on relit Modbus pour rafraîchir les variables OPC-UA. Dans
                # l'autre ordre, une commande écrite par un client OPC-UA entre
                # deux cycles serait écrasée par la relecture avant d'avoir pu
                # être transmise au Modbus (effacée avant même d'être appliquée).
                self.push_opcua_commands_to_modbus()
                self.poll_modbus_to_opcua()
                time.sleep(config.GATEWAY_POLL_INTERVAL_S)
        except KeyboardInterrupt:
            pass
        finally:
            self.server.stop()
            self.client.close()

    def stop(self):
        self._running = False


if __name__ == "__main__":
    Gateway().run()

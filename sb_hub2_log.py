"""SwitchBot Hub2から気温とかを読むよ."""

import argparse
import configparser
import requests.exceptions  # type: ignore
import subprocess
import sys
import time
import typing as typ
from datetime import datetime
from switchbot import SwitchBot  # type: ignore


class Hub2Log:
    """SwitchBot Hub2から気温等を読むクラス."""

    def __init__(self) -> None:
        """初期化."""
        inifile: configparser.ConfigParser = configparser.ConfigParser()
        inifile.read("sb_hub2_log.ini", "utf-8")
        self.inifile: configparser.ConfigParser = inifile
        self.token: str = inifile.get("hub2", "token")
        self.secret: str = inifile.get("hub2", "secret")
        self.retry: int = inifile.getint("hub2", "retry", fallback=1)
        device_ids: list[str] = inifile.get("hub2", "device_ids").split(",")
        self.zabbix_server: str | None = inifile.get("zabbix", "server")
        self.zabbix_port: int = inifile.getint("zabbix", "port", fallback=10051)
        self.zabbix_host: str | None = inifile.get("zabbix", "host")
        self.zabbix_key_prefix: str = inifile.get("zabbix", "key_prefix", fallback="sb")
        self.zabbix_trap: typ.TextIO | None = None
        self.zabbix_command: typ.List[str] = [
            "zabbix_sender",
            "-z",
            self.zabbix_server,
            "-p",
            f"{self.zabbix_port}",
            "-s",
            self.zabbix_host,
            "-i",
            "zabbix.trap",
        ]
        self.temp_flag: bool = False

        self.devices: dict = {}
        switchbot = SwitchBot(self.token, self.secret)
        devices: list = switchbot.devices()
        for device in devices:
            if device.id in device_ids:
                self.devices[device.id] = device
                device_ids.remove(device.id)
        if len(device_ids) > 0:
            print(f"device {device_ids} not found.")
            sys.exit(1)

    def main(self) -> None:
        """メイン処理."""
        parser: argparse.ArgumentParser = argparse.ArgumentParser()
        parser.add_argument(
            "-t", "--temp", action="store_true", help="log Raspberry pi temp"
        )

        args: argparse.Namespace = parser.parse_args()

        self.temp_flag = args.temp

        try:
            self.task()
        except KeyboardInterrupt:
            pass

    def add_zabbix(self, key: str, value: typ.Any) -> None:
        """zabbixに送信するデータを追加する.

        Args:
            key: キー
            value: 値
        """
        if self.zabbix_trap:
            print(f"- {self.zabbix_key_prefix}.{key} {value}", file=self.zabbix_trap)

    def log_temp(self) -> float:
        """温度を記録する.

        Returns:
            CPU温度
        """
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp: float = int(f.readline()) / 1000

        self.add_zabbix("cpu_temperature", temp)
        return temp

    def log_hub2(self) -> dict:
        """Hub2のデータを読む.

        Returns:
            dict
        """
        results: dict = {}
        switchbot = SwitchBot(self.token, self.secret)
        for device in self.devices.values():
            for retry in range(self.retry):
                try:
                    device.client = switchbot.client
                    status: dict = device.status()
                    results[device.id] = status
                    self.add_zabbix(f"{device.id}.humidity", status["humidity"])
                    self.add_zabbix(f"{device.id}.temperature", status["temperature"])
                    self.add_zabbix(f"{device.id}.light_level", status["light_level"])
                    break
                except RuntimeError as e:
                    print(f"{datetime.now()} {device.id}:", e, flush=True)
                    time.sleep(1)
                except requests.exceptions.ConnectionError as e:
                    print(f"{datetime.now()} {device.id}:", e, flush=True)
                    break
        return results

    def task(self) -> None:
        """1分間隔で繰り返し実行."""
        interval: int = 60
        while True:
            if self.zabbix_server:
                self.zabbix_trap = open("zabbix.trap", "wt")
            next_time: int = (int(time.time()) // interval + 1) * interval
            if self.temp_flag:
                self.log_temp()
            self.log_hub2()
            if self.zabbix_trap:
                self.zabbix_trap.close()
                with open("zabbix.log", "wt") as zabbix_log:
                    subprocess.run(
                        self.zabbix_command, stdout=zabbix_log, stderr=subprocess.STDOUT
                    )
                self.zabbix_trap = None
            now: float = time.time()
            if now < next_time:
                time.sleep(next_time - now)


if __name__ == "__main__":
    Hub2Log().main()

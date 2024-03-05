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


def log(text: str):
    """ログ出力.

    Args:
        text: ログ出力文字列
    """
    timestamp: str = f"{datetime.now()}"[:-3]
    print(f"{timestamp} {text}", flush=True)


class Hub2Log:
    """SwitchBot Hub2から気温等を読むクラス."""

    def __init__(self) -> None:
        """初期化."""
        inifile: configparser.ConfigParser = configparser.ConfigParser()
        inifile.read("sb_hub2_log.ini", "utf-8")
        self.inifile: configparser.ConfigParser = inifile
        self.token: str = inifile.get("hub2", "token")
        self.secret: str = inifile.get("hub2", "secret")
        self.retry: int = inifile.getint("hub2", "retry", fallback=3)
        self.interval: int = inifile.getint("hub2", "interval", fallback=300)
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
                    log(f"{retry} {device.id} {e}")
                    time.sleep(1)
                except requests.exceptions.ConnectionError as e:
                    log(f"{retry} {device.id} {e}")
                    break
        return results

    def task(self) -> None:
        """interval(秒)間隔で繰り返し実行."""
        next_time: int = (int(time.time()) // self.interval + 1) * self.interval
        while True:
            now: float = time.time()
            if now < next_time:
                time.sleep(next_time - now)
                next_time += self.interval
            else:
                next_time = (int(now) // self.interval + 1) * self.interval
            if self.zabbix_server:
                self.zabbix_trap = open("zabbix.trap", "wt")
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


if __name__ == "__main__":
    Hub2Log().main()

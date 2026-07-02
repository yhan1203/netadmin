"""网段扫描 — 发现网络中的设备（ping + 端口扫描 + 厂商识别）"""

from __future__ import annotations

import concurrent.futures
import ipaddress
import socket
import subprocess
import time


class NetworkScanner:
    """网络设备发现"""

    def __init__(self) -> None:
        self._results: list[dict] = []

    def scan(self, subnet: str, timeout: int = 3, max_workers: int = 50) -> list[dict]:
        """扫描网段

        Args:
            subnet: CIDR 格式，如 "192.168.1.0/24"
            timeout: Ping 超时（秒）
            max_workers: 并发数

        Returns:
            list[dict]: 发现的设备列表
        """
        network = ipaddress.ip_network(subnet, strict=False)
        # /31 和 /32 的 hosts() 返回空列表，需要 fallback
        network_hosts = list(network.hosts())
        if not network_hosts:
            # /31 子网只有 2 个可用 IP，/32 只有 1 个
            hosts = [str(network.network_address)]
            if network.prefixlen == 31:
                hosts.append(str(network.broadcast_address))
        else:
            hosts = [str(ip) for ip in network_hosts]

        self._results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            fut_to_ip = {
                executor.submit(self._probe, ip, timeout): ip
                for ip in hosts
            }
            for fut in concurrent.futures.as_completed(fut_to_ip):
                result = fut.result()
                if result:
                    self._results.append(result)

        self._results.sort(key=lambda d: [int(o) for o in d["ip"].split(".")])
        return self._results

    @staticmethod
    def _scan_port(ip: str, port: int, timeout: int) -> int | None:
        """扫描单个端口"""
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return port
        except (OSError, socket.timeout):
            return None

    def _probe(self, ip: str, timeout: int) -> dict | None:
        """探测单台设备"""
        start = time.time()

        if not self._ping(ip, timeout):
            return None

        elapsed = round(time.time() - start, 2)

        # 找主机名
        hostname = self._resolve_hostname(ip)

        # 并发扫描端口
        open_ports = self._scan_ports(ip, timeout=min(2, timeout))

        # 识别厂商（通过端口 banner）
        vendor = self._identify_vendor(ip, open_ports)

        return {
            "ip": ip,
            "hostname": hostname or "",
            "vendor": vendor,
            "open_ports": ",".join(str(p) for p in open_ports) if open_ports else "",
            "response_time": f"{elapsed}s",
        }

    @staticmethod
    def _ping(ip: str, timeout: int) -> bool:
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", str(timeout), ip],
                capture_output=True,
                text=True,
                timeout=timeout + 2,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    @staticmethod
    def _resolve_hostname(ip: str) -> str | None:
        try:
            return socket.gethostbyaddr(ip)[0]
        except (socket.herror, socket.timeout, OSError):
            return None

    @staticmethod
    def _scan_ports(ip: str, timeout: int = 2) -> list[int]:
        """并发扫描常见运维端口"""
        common_ports = [22, 23, 161, 443, 80, 8443]
        open_ports: list[int] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(common_ports)) as executor:
            fut_to_port = {
                executor.submit(NetworkScanner._scan_port, ip, port, timeout): port
                for port in common_ports
            }
            for fut in concurrent.futures.as_completed(fut_to_port):
                result = fut.result()
                if result is not None:
                    open_ports.append(result)

        return sorted(open_ports)

    @staticmethod
    def _identify_vendor(ip: str, open_ports: list[int]) -> str:
        """通过开放端口和 SSH banner 猜测厂商"""
        if 22 not in open_ports and 23 not in open_ports:
            return "unknown"

        # 尝试 SSH banner grab
        try:
            with socket.create_connection((ip, 22), timeout=3) as sock:
                banner = sock.recv(1024).decode("utf-8", errors="ignore").lower()
                if "huawei" in banner or "vrp" in banner:
                    return "huawei"
                if "cisco" in banner or "ios" in banner:
                    return "cisco"
        except (OSError, socket.timeout, UnicodeDecodeError):
            pass

        return "unknown"


def quick_scan(subnet: str) -> list[dict]:
    """便捷扫描函数"""
    scanner = NetworkScanner()
    return scanner.scan(subnet)
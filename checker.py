"""ipcheck 检测封装：直接调用 ipcheck 库函数，返回结构化结果。"""

import sys
import io
import subprocess

if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

if sys.platform == "win32":
    _original_run = subprocess.run

    def _silent_run(*args, **kwargs):
        if "creationflags" not in kwargs:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        return _original_run(*args, **kwargs)

    subprocess.run = _silent_run

from ipcheck.cli import (
    get_lan_ip,
    get_ipv6,
    get_dns_servers,
    get_public_info,
    get_ip_risk,
    get_proxy_envs,
    get_cli_tz_name,
    KNOWN_DNS,
    ANSI_RE,
    make_zone,
)

try:
    from ipcheck.cli import get_system_proxy
except ImportError:
    get_system_proxy = lambda: None

try:
    from ipcheck.cli import get_tun_vpn_status
except ImportError:
    get_tun_vpn_status = lambda: (None, [])

try:
    from ipcheck.cli import get_stopforumspam
except ImportError:
    get_stopforumspam = None
import datetime


def _strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", str(s))


def is_cn_dns(servers: list[str]) -> bool:
    return any("(CN)" in KNOWN_DNS.get(d, "") for d in servers)


def run_check() -> dict:
    """执行完整检测，返回结构化结果 dict。"""
    result = {
        "lan_ip": "",
        "ipv6": None,
        "ipv6_leaked": False,
        "dns_servers": [],
        "dns_cn": False,
        "public_ip": "",
        "country": "",
        "region": "",
        "city": "",
        "isp": "",
        "ip_timezone": "",
        "proxy_envs": {},
        "system_proxy": None,
        "tun_vpn": False,
        "ip_proxy": False,
        "ip_hosting": False,
        "risk_score": None,
        "risk_display": "",
        "cli_timezone": "",
        "tz_matched": None,
        "conclusions": [],
        "overall_safe": True,
    }

    result["lan_ip"] = _strip_ansi(get_lan_ip())

    ipv6 = get_ipv6()
    result["ipv6"] = ipv6
    result["ipv6_leaked"] = ipv6 is not None

    dns = get_dns_servers()
    result["dns_servers"] = dns
    result["dns_cn"] = is_cn_dns(dns)

    pub = get_public_info()
    pub_ok = pub.get("status") == "success"
    if pub_ok:
        result["public_ip"] = pub.get("query", "")
        result["country"] = pub.get("country", "")
        result["region"] = pub.get("regionName", "")
        result["city"] = pub.get("city", "")
        result["isp"] = pub.get("isp", "")
        result["ip_timezone"] = pub.get("timezone", "")
        result["ip_proxy"] = bool(pub.get("proxy"))
        result["ip_hosting"] = bool(pub.get("hosting"))

    result["proxy_envs"] = get_proxy_envs()

    system_proxy = get_system_proxy()
    result["system_proxy"] = system_proxy

    tun_active, _ = get_tun_vpn_status()
    result["tun_vpn"] = bool(tun_active)

    if pub_ok and (result["ip_proxy"] or result["ip_hosting"]):
        risk_display, risk_score = get_ip_risk(result["public_ip"])
        result["risk_display"] = _strip_ansi(risk_display)
        result["risk_score"] = risk_score

    tz_name, is_iana = get_cli_tz_name()
    cli_offset = datetime.datetime.now().astimezone().utcoffset()
    result["cli_timezone"] = tz_name

    pub_tz = pub.get("timezone") if pub_ok else None
    if pub_tz:
        pub_zi = make_zone(pub_tz)
        pub_offset = datetime.datetime.now(pub_zi).utcoffset() if pub_zi else None
        if is_iana:
            result["tz_matched"] = tz_name == pub_tz
        elif pub_offset is not None:
            result["tz_matched"] = cli_offset == pub_offset

    # conclusions
    conclusions = []
    has_bad = False

    if result["ipv6_leaked"]:
        conclusions.append(("bad", "IPv6 泄露，暴露真实地址"))
        has_bad = True
    else:
        conclusions.append(("ok", "IPv6 已禁用，无泄露风险"))

    if result["dns_cn"]:
        conclusions.append(("warn", "DNS 使用国内服务商，可能暴露真实位置"))
        has_bad = True
    elif not dns:
        conclusions.append(("warn", "DNS 获取失败，无法评估"))
    else:
        conclusions.append(("ok", "DNS 未检测到国内服务商"))

    if not pub_ok:
        conclusions.append(("warn", "IP 信息获取失败，无法评估风险"))
    elif result["ip_proxy"] or result["ip_hosting"]:
        score = result["risk_score"]
        if score is not None:
            if score >= 70:
                conclusions.append(("bad", f"IP 风险高（{score}/100），建议更换节点"))
                has_bad = True
            elif score >= 30:
                conclusions.append(("warn", f"IP 风险中等（{score}/100），建议关注"))
            else:
                conclusions.append(("ok", f"IP 风险低（{score}/100）"))
        else:
            conclusions.append(("warn", "IP 为机房/代理，未查到风险分数"))
    else:
        conclusions.append(("ok", "IP 正常，无风险标记"))

    if result["tz_matched"] is True:
        conclusions.append(("ok", "时区一致"))
    elif result["tz_matched"] is False:
        conclusions.append(("bad", "时区不一致，建议调整"))
        has_bad = True
    else:
        conclusions.append(("warn", "时区无法比对"))

    result["conclusions"] = conclusions
    result["overall_safe"] = not has_bad

    return result

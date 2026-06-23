"""
audit.py
Module d'audit d'obsolescence - NTL-SysToolbox

Fonctions :
  1. Scan réseau sur une plage IP (détecte les hôtes actifs + ports ouverts)
  2. Détection de l'OS à partir des ports ouverts
  3. Comparaison avec la base EOL (fin de vie)
  4. Génération d'un rapport JSON + CSV

Plage NTL : 192.168.10.0/24
"""

import socket
import json
import csv
import os
import ipaddress
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed


# ─── Ports à tester et leur signification ────────────────────────────────────

PORTS_QUICK = {
    22:   "SSH (Linux/Unix)",
    80:   "HTTP",
    443:  "HTTPS",
    3306: "MySQL/MariaDB",
    3389: "RDP (Windows)",
    5985: "WinRM HTTP (Windows)",
    5986: "WinRM HTTPS (Windows)",
    389:  "LDAP (Active Directory)",
    53:   "DNS"
}


def detect_os_from_ports(open_ports):
    """
    Détermine l'OS probable d'un hôte en fonction des ports ouverts.
    Logique simple mais efficace pour un parc homogène comme NTL.
    """
    if 5985 in open_ports or 3389 in open_ports or 389 in open_ports:
        return "Windows"
    elif 22 in open_ports:
        return "Linux"
    elif 53 in open_ports and 389 not in open_ports:
        return "Linux"  # DNS seul sans LDAP → probablement Linux
    else:
        return "Inconnu"


def check_port(ip, port, timeout=1.0):
    """Teste si un port TCP est ouvert sur une IP. Retourne True/False."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((str(ip), port))
        sock.close()
        return result == 0  # 0 = connexion réussie
    except Exception:
        return False


def scan_host(ip, ports_dict, timeout=1.0):
    """
    Scanne tous les ports d'une IP.
    Retourne None si l'hôte ne répond sur aucun port (considéré inactif).
    """
    ip_str = str(ip)
    open_ports = []

    for port in ports_dict.keys():
        if check_port(ip_str, port, timeout):
            open_ports.append(port)

    if not open_ports:
        return None  # Hôte inactif ou inaccessible

    os_type = detect_os_from_ports(open_ports)
    services = [ports_dict[p] for p in open_ports]

    return {
        "ip": ip_str,
        "os_detected": os_type,
        "open_ports": open_ports,
        "services": services,
        "active": True
    }


def scan_network(network_cidr, timeout=1.0, max_workers=50):
    """
    Scanne toute une plage réseau en parallèle (jusqu'à 50 threads simultanés).

    Exemple : scan_network("192.168.10.0/24") scanne les 254 IPs de ce sous-réseau.

    Retourne la liste des hôtes actifs avec leurs ports et OS détecté.
    """
    network = ipaddress.IPv4Network(network_cidr, strict=False)
    hosts_to_scan = list(network.hosts())  # Exclut adresse réseau et broadcast

    print(f"\n  Scan du réseau {network_cidr} ({len(hosts_to_scan)} adresses)...")
    print(f"  Ports testés : {list(PORTS_QUICK.keys())}")

    active_hosts = []
    scanned = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Lance tous les scans en parallèle
        future_to_ip = {
            executor.submit(scan_host, ip, PORTS_QUICK, timeout): ip
            for ip in hosts_to_scan
        }

        for future in as_completed(future_to_ip):
            scanned += 1
            if scanned % 50 == 0:
                print(f"  ... {scanned}/{len(hosts_to_scan)} IPs scannées")

            result = future.result()
            if result is not None:
                active_hosts.append(result)
                print(f"  🔍 Trouvé : {result['ip']} - {result['os_detected']} - ports {result['open_ports']}")

    active_hosts.sort(key=lambda x: ipaddress.IPv4Address(x["ip"]))
    print(f"\n  ✅ Scan terminé : {len(active_hosts)} hôtes actifs sur {len(hosts_to_scan)} IPs")
    return active_hosts


# ─── Vérification EOL ────────────────────────────────────────────────────────

def load_eol_database(eol_db_path="config/eol_database.json"):
    """Charge la base de données des fins de vie depuis le fichier JSON."""
    with open(eol_db_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["os_versions"]


def check_eol_status(os_name, os_version, eol_db):
    """
    Cherche le statut EOL d'un OS/version dans la base.
    Retourne un dictionnaire avec le statut et la date de fin de vie.
    """
    os_name_lower = os_name.lower()

    for entry in eol_db:
        entry_os = entry["os"].lower()
        entry_version = str(entry["version"]).lower()

        # Correspondance flexible : "ubuntu 22.04" matche "ubuntu" + "22.04"
        if entry_os in os_name_lower or os_name_lower in entry_os:
            if entry_version in str(os_version).lower():
                return {
                    "os": entry["os"],
                    "version": entry["version"],
                    "eol_date": entry["eol_date"],
                    "status": entry["status"]
                }

    return {
        "os": os_name,
        "version": os_version,
        "eol_date": "Inconnu",
        "status": "NON_RENSEIGNE"
    }


def check_eol_from_csv(csv_path, eol_db_path="config/eol_database.json", output_dir="outputs/reports"):
    """
    Lit un fichier CSV contenant une liste de machines avec leur OS/version,
    vérifie le statut EOL de chacune, et génère un rapport.

    Format CSV attendu : ip,hostname,os,version
    """
    eol_db = load_eol_database(eol_db_path)
    results = []

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            eol_info = check_eol_status(
                row.get("os", "Inconnu"),
                row.get("version", "Inconnu"),
                eol_db
            )
            results.append({**row, **eol_info})

    return results


# ─── Génération du rapport ───────────────────────────────────────────────────

def generate_audit_report(network_cidr, eol_db_path="config/eol_database.json",
                           output_dir="outputs/reports"):
    """
    Fonction principale du module Audit :
    1. Scanne le réseau NTL (192.168.10.0/24)
    2. Pour chaque hôte actif, vérifie le statut EOL selon l'OS détecté
    3. Génère un rapport JSON complet + un résumé CSV

    C'est cette fonction qu'on appellera depuis main.py
    """
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Appareils NTL connus (pour enrichir le rapport avec les noms réels)
    known_hosts = {
        "192.168.10.10": {"name": "DC01",     "role": "Controleur de domaine principal"},
        "192.168.10.11": {"name": "DC02",     "role": "Controleur de domaine secondaire"},
        "192.168.10.21": {"name": "WMS-DB",   "role": "Base MySQL WMS"},
        "192.168.10.22": {"name": "WMS-APP",  "role": "Application WMS"},
        "192.168.10.40": {"name": "IPBX-VM",  "role": "Serveur IPBX (telephonie)"},
        "192.168.10.50": {"name": "SUPER-01", "role": "Supervision Zabbix"},
        "192.168.10.254": {"name": "FW-Siège", "role": "Pare-feu FortiGate 80D"},
    }

    # Informations de version connues pour enrichir le rapport
    known_versions = {
        "192.168.10.10": {"os": "Windows Server", "version": "2019"},
        "192.168.10.11": {"os": "Windows Server", "version": "2019"},
        "192.168.10.21": {"os": "Ubuntu",          "version": "22.04"},
        "192.168.10.22": {"os": "Ubuntu",          "version": "22.04"},
        "192.168.10.40": {"os": "Ubuntu",          "version": "22.04"},
        "192.168.10.50": {"os": "Ubuntu",          "version": "22.04"},
    }

    # Aussi : inventaire manuel pour composants non-VM (ESXi, pare-feux, switchs)
    manual_inventory = [
        {
            "ip": "192.168.10.1",
            "name": "Hyperviseur",
            "role": "Dell PowerEdge R630 - VMware ESXi",
            "os": "VMware ESXi",
            "version": "6.5",
            "source": "inventaire_manuel"
        },
        {
            "ip": "192.168.10.254",
            "name": "FW-Siege",
            "role": "Pare-feu perimetre - Fortinet FortiGate 80D",
            "os": "FortiOS",
            "version": "Inconnu",
            "source": "inventaire_manuel"
        }
    ]

    eol_db = load_eol_database(eol_db_path)

    # ── Étape 1 : Scan réseau ──
    active_hosts = scan_network(network_cidr)

    # ── Étape 2 : Enrichissement + vérification EOL ──
    enriched_hosts = []
    for host in active_hosts:
        ip = host["ip"]

        # Enrichissement avec noms connus
        if ip in known_hosts:
            host["name"] = known_hosts[ip]["name"]
            host["role"] = known_hosts[ip]["role"]
        else:
            host["name"] = "Inconnu"
            host["role"] = "Non référencé"

        # Enrichissement avec versions connues
        if ip in known_versions:
            host["os_name"] = known_versions[ip]["os"]
            host["os_version"] = known_versions[ip]["version"]
        else:
            host["os_name"] = host["os_detected"]
            host["os_version"] = "Inconnu"

        # Vérification EOL
        eol_info = check_eol_status(host["os_name"], host["os_version"], eol_db)
        host["eol_date"] = eol_info["eol_date"]
        host["eol_status"] = eol_info["status"]

        enriched_hosts.append(host)

    # ── Ajouter l'inventaire manuel (ESXi, pare-feux) ──
    for item in manual_inventory:
        eol_info = check_eol_status(item["os"], item["version"], eol_db)
        item["eol_status"] = eol_info["status"]
        item["eol_date"] = eol_info["eol_date"]
        item["active"] = True
        item["open_ports"] = []
        item["os_detected"] = item["os"]
        enriched_hosts.append(item)

    # ── Étape 3 : Statistiques du rapport ──
    stats = {
        "total_hosts": len(enriched_hosts),
        "eol_count": sum(1 for h in enriched_hosts if h.get("eol_status") == "EOL"),
        "bientot_eol_count": sum(1 for h in enriched_hosts if h.get("eol_status") == "BIENTOT_EOL"),
        "supported_count": sum(1 for h in enriched_hosts if h.get("eol_status") == "SUPPORTE"),
        "unknown_count": sum(1 for h in enriched_hosts if h.get("eol_status") in ("NON_RENSEIGNE", "UNKNOWN")),
    }

    # ── Étape 4 : Export JSON ──
    json_path = os.path.join(output_dir, f"audit_report_{timestamp}.json")
    report_data = {
        "timestamp": datetime.now().isoformat(),
        "network_scanned": network_cidr,
        "statistics": stats,
        "hosts": enriched_hosts
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)
    print(f"\n  📄 Rapport JSON : {json_path}")

    # ── Étape 5 : Export CSV ──
    csv_path = os.path.join(output_dir, f"audit_report_{timestamp}.csv")
    csv_fields = ["ip", "name", "role", "os_name", "os_version",
                  "eol_status", "eol_date", "open_ports"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        for h in enriched_hosts:
            h_copy = dict(h)
            h_copy["open_ports"] = str(h_copy.get("open_ports", []))
            writer.writerow({k: h_copy.get(k, "") for k in csv_fields})
    print(f"  📄 Rapport CSV  : {csv_path}")

    # ── Affichage résumé ──
    print(f"\n  ═══════════════════════════════════════")
    print(f"  RÉSUMÉ AUDIT D'OBSOLESCENCE - NTL")
    print(f"  ═══════════════════════════════════════")
    print(f"  Total hôtes détectés : {stats['total_hosts']}")
    print(f"  ❌ EOL (non supporté)  : {stats['eol_count']}")
    print(f"  ⚠️  Bientôt EOL        : {stats['bientot_eol_count']}")
    print(f"  ✅ Supporté           : {stats['supported_count']}")
    print(f"  ❓ Non renseigné      : {stats['unknown_count']}")
    print(f"  ═══════════════════════════════════════")

    return json_path, csv_path, report_data

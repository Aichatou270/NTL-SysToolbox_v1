"""
main.py - NTL-SysToolbox
Point d'entrée principal. Lance le menu interactif.

Usage :
    python main.py

Prérequis :
    pip install paramiko pywinrm
"""

import json
import os
import sys
from datetime import datetime

# ── Chargement de la configuration ──────────────────────────────────────────

def load_config(config_path="config/config.json"):
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Affichage du menu ────────────────────────────────────────────────────────

def print_banner():
    print("\n" + "═" * 45)
    print("       NTL-SysToolbox v1.0")
    print("       NordTransit Logistics - Siège Lille")
    print("═" * 45)


def print_menu():
    print("\n  1. Diagnostic système (DC01/DC02/WMS-DB)")
    print("  2. Sauvegarde WMS (dump SQL)")
    print("  3. Export CSV d'une table WMS")
    print("  4. Audit d'obsolescence du réseau")
    print("  5. Quitter")
    print()


# ── Option 1 : Diagnostic ────────────────────────────────────────────────────

def run_diagnostic(config):
    print("\n─── MODULE DIAGNOSTIC ─────────────────────────")
    print("  Cibles : DC01 (Windows), DC02 (Windows), WMS-DB (Linux)")

    from src.modules.diagnostic.diagnostic_windows import get_windows_metrics, check_ad_dns
    from src.modules.diagnostic.diagnostic_linux import get_linux_metrics, check_mysql

    servers = config["servers"]
    all_results = {}
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = config.get("output_dir", "outputs") + "/reports"
    os.makedirs(output_dir, exist_ok=True)

    # ── DC01 : métriques Windows + AD/DNS ──
    dc01 = servers["dc01"]
    print(f"\n[1/4] DC01 - {dc01['ip']}")
    metrics_dc01 = get_windows_metrics(dc01["ip"], dc01["username"])
    ad_dc01 = check_ad_dns(dc01["ip"], dc01["username"])
    all_results["DC01"] = {**metrics_dc01, "ad_dns": ad_dc01}

    # ── DC02 : métriques Windows + AD/DNS ──
    dc02 = servers["dc02"]
    print(f"\n[2/4] DC02 - {dc02['ip']}")
    metrics_dc02 = get_windows_metrics(dc02["ip"], dc02["username"])
    ad_dc02 = check_ad_dns(dc02["ip"], dc02["username"])
    all_results["DC02"] = {**metrics_dc02, "ad_dns": ad_dc02}

    # ── WMS-DB : métriques Linux ──
    wms = servers["wms-db"]
    print(f"\n[3/4] WMS-DB - {wms['ip']}")
    metrics_wms = get_linux_metrics(wms["ip"], wms["username"])
    all_results["WMS-DB"] = metrics_wms

    # ── WMS-DB : vérification MariaDB/MySQL ──
    print(f"\n[4/4] MySQL/MariaDB sur WMS-DB - {wms['ip']}")
    mysql_result = check_mysql(wms["ip"], wms["username"])
    all_results["WMS-DB"]["mysql"] = mysql_result

    # ── Sauvegarde du rapport JSON ──
    report_path = os.path.join(output_dir, f"diagnostic_report_{timestamp}.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print(f"\n  ✅ Rapport diagnostic sauvegardé : {report_path}")
    return all_results


# ── Option 2 : Sauvegarde SQL ────────────────────────────────────────────────

def run_backup_sql(config):
    print("\n─── MODULE SAUVEGARDE WMS (SQL) ───────────────")
    from src.modules.backup.backup import backup_sql

    wms = config["servers"]["wms-db"]
    mysql_cfg = config["mysql"]
    output_dir = config.get("output_dir", "outputs") + "/reports"

    sql_path, report = backup_sql(
        host=wms["ip"],
        ssh_user=wms["username"],
        db_name=mysql_cfg["database"],
        db_user=mysql_cfg["username"],
        output_dir=output_dir
    )
    return sql_path, report


# ── Option 3 : Export CSV ────────────────────────────────────────────────────

def run_export_csv(config):
    print("\n─── MODULE EXPORT CSV ─────────────────────────")
    from src.modules.backup.backup import export_csv

    wms = config["servers"]["wms-db"]
    mysql_cfg = config["mysql"]
    output_dir = config.get("output_dir", "outputs") + "/reports"

    table_name = input("  Nom de la table à exporter : ").strip()
    if not table_name:
        print("  ⚠️  Nom de table vide, annulé.")
        return

    csv_path, report = export_csv(
        host=wms["ip"],
        ssh_user=wms["username"],
        db_name=mysql_cfg["database"],
        db_user=mysql_cfg["username"],
        table_name=table_name,
        output_dir=output_dir
    )
    return csv_path, report


# ── Option 4 : Audit d'obsolescence ─────────────────────────────────────────

def run_audit(config):
    print("\n─── MODULE AUDIT D'OBSOLESCENCE ───────────────")
    from src.modules.audit.audit import generate_audit_report

    scan_ranges = config["audit"]["scan_ranges"]
    output_dir = config.get("output_dir", "outputs") + "/reports"

    print(f"  Plages à scanner : {scan_ranges}")
    confirm = input("  Lancer le scan ? (o/n) : ").strip().lower()
    if confirm != "o":
        print("  Annulé.")
        return

    for network in scan_ranges:
        json_path, csv_path, report_data = generate_audit_report(
            network_cidr=network,
            eol_db_path="config/eol_database.json",
            output_dir=output_dir
        )

    return json_path, csv_path


# ── Boucle principale ────────────────────────────────────────────────────────

def main():
    config = load_config()
    print_banner()

    while True:
        print_menu()
        choice = input("  Choisissez une option (1-5) : ").strip()

        if choice == "1":
            run_diagnostic(config)

        elif choice == "2":
            run_backup_sql(config)

        elif choice == "3":
            run_export_csv(config)

        elif choice == "4":
            run_audit(config)

        elif choice == "5":
            print("\n  Au revoir !\n")
            sys.exit(0)

        else:
            print("  ⚠️  Option invalide, tapez 1, 2, 3, 4 ou 5.")

        input("\n  [Appuyez sur Entrée pour revenir au menu]")


if __name__ == "__main__":
    main()

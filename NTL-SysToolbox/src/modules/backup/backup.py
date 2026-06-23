"""
backup.py
Module de sauvegarde WMS - NTL-SysToolbox

Fonctions :
  1. Dump complet de la base WMS au format SQL (via mysqldump/mariadb-dump)
  2. Export d'une table spécifique au format CSV

Cible : WMS-DB (192.168.10.21) - Ubuntu 22.04 - MariaDB
"""

import paramiko
import getpass
import os
import json
from datetime import datetime


# ─── Helpers SSH ────────────────────────────────────────────────────────────

def get_ssh_password(username, host):
    pwd = os.getenv("NTL_SSH_PASSWORD")
    if not pwd:
        pwd = getpass.getpass(f"  Mot de passe SSH pour {username}@{host} : ")
    return pwd


def connect_ssh(host, username, password, port=22):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=host, port=port, username=username,
                   password=password, timeout=15)
    return client


def run_command(client, command):
    stdin, stdout, stderr = client.exec_command(command)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out.strip(), err.strip()


# ─── Dump SQL ────────────────────────────────────────────────────────────────

def backup_sql(host, ssh_user, db_name, db_user, output_dir="outputs/reports"):
    """
    Effectue un dump complet de la base MariaDB/MySQL via SSH.

    - Se connecte en SSH à WMS-DB
    - Exécute mysqldump sur la machine distante
    - Rapatrie le fichier .sql localement dans outputs/reports/
    - Génère un rapport JSON de traçabilité

    Retourne le chemin du fichier SQL sauvegardé.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sql_filename = f"backup_wms_{timestamp}.sql"
    sql_filepath = os.path.join(output_dir, sql_filename)
    report_filepath = os.path.join(output_dir, f"backup_report_{timestamp}.json")

    os.makedirs(output_dir, exist_ok=True)

    report = {
        "timestamp": datetime.now().isoformat(),
        "type": "SQL_DUMP",
        "source_host": host,
        "database": db_name,
        "output_file": sql_filepath,
        "status": "UNKNOWN"
    }

    print(f"\n  Connexion SSH à {host} pour la sauvegarde SQL...")
    ssh_password = get_ssh_password(ssh_user, host)

    # Mot de passe MySQL (optionnel si accès unix socket sans mdp)
    mysql_password = os.getenv("NTL_MYSQL_PASSWORD") or ""
    mysql_pass_option = f"-p'{mysql_password}'" if mysql_password else ""

    try:
        client = connect_ssh(host, ssh_user, ssh_password)
        print(f"  ✅ Connecté à {host}")

        # Commande mysqldump avec options de sécurité :
        # --single-transaction : snapshot cohérent sans verrouiller les tables InnoDB
        # --quick              : lit les lignes une à une (économise la RAM)
        # --skip-lock-tables   : pas de verrous sur les tables MyISAM
        dump_command = (
            f"sudo mysqldump --single-transaction --quick "
            f"{db_name} 2>/dev/null || "
            f"sudo mariadb-dump --single-transaction --quick "
            f"{db_name} 2>/dev/null"
        )

        print(f"  Exécution du dump sur {host}...")
        out, err = run_command(client, dump_command)

        if out and len(out) > 100:
            # Le dump contient du contenu : on le sauvegarde localement
            with open(sql_filepath, "w", encoding="utf-8") as f:
                f.write(out)

            file_size = os.path.getsize(sql_filepath)
            report["status"] = "OK"
            report["file_size_bytes"] = file_size
            report["file_size_human"] = f"{round(file_size/1024, 1)} Ko"
            print(f"  ✅ Dump SQL sauvegardé : {sql_filepath} ({report['file_size_human']})")
        else:
            report["status"] = "AVERTISSEMENT"
            report["warning"] = "Dump vide ou trop petit - vérifier les droits MySQL"
            if err:
                report["error_detail"] = err
            print(f"  ⚠️  Dump vide. Erreur : {err}")

        client.close()

    except Exception as e:
        report["status"] = "ERREUR"
        report["error"] = str(e)
        print(f"  ❌ Erreur sauvegarde SQL : {e}")

    # Sauvegarde du rapport JSON de traçabilité
    with open(report_filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"  📄 Rapport de traçabilité : {report_filepath}")

    return sql_filepath, report


# ─── Export CSV ──────────────────────────────────────────────────────────────

def export_csv(host, ssh_user, db_name, db_user, table_name, output_dir="outputs/reports"):
    """
    Exporte une table MariaDB/MySQL au format CSV via SSH.

    - Se connecte en SSH à WMS-DB
    - Exécute une requête SQL pour lire la table
    - Récupère les données en format tabulé et les convertit en CSV
    - Sauvegarde le fichier localement

    Retourne le chemin du fichier CSV généré.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = f"export_{table_name}_{timestamp}.csv"
    csv_filepath = os.path.join(output_dir, csv_filename)

    os.makedirs(output_dir, exist_ok=True)

    report = {
        "timestamp": datetime.now().isoformat(),
        "type": "CSV_EXPORT",
        "source_host": host,
        "database": db_name,
        "table": table_name,
        "output_file": csv_filepath,
        "status": "UNKNOWN"
    }

    print(f"\n  Export CSV de la table '{table_name}' depuis {host}...")
    ssh_password = get_ssh_password(ssh_user, host)
    mysql_password = os.getenv("NTL_MYSQL_PASSWORD") or ""
    mysql_pass_option = f"-p'{mysql_password}'" if mysql_password else ""

    try:
        client = connect_ssh(host, ssh_user, ssh_password)

        # mysql -B : mode batch (séparateurs tabulation, pas de cadres ASCII)
        # -e : exécute la requête SQL
        export_command = (
            f"sudo mysql -B -e "
            f"'SELECT * FROM {table_name};' {db_name} 2>/dev/null || "
            f"sudo mariadb -B -e "
            f"'SELECT * FROM {table_name};' {db_name} 2>/dev/null"
        )

        out, err = run_command(client, export_command)

        if out and "\t" in out:
            # Convertit les tabulations en virgules pour le format CSV
            lines = out.split("\n")
            csv_lines = [line.replace("\t", ",") for line in lines if line.strip()]

            with open(csv_filepath, "w", encoding="utf-8") as f:
                f.write("\n".join(csv_lines))

            row_count = len(csv_lines) - 1  # -1 pour l'en-tête
            report["status"] = "OK"
            report["rows_exported"] = row_count
            print(f"  ✅ Export CSV : {csv_filepath} ({row_count} lignes)")
        else:
            report["status"] = "AVERTISSEMENT"
            report["warning"] = f"Table vide ou inaccessible : {table_name}"
            if err:
                report["error_detail"] = err
            print(f"  ⚠️  Table vide ou erreur : {err}")

        client.close()

    except Exception as e:
        report["status"] = "ERREUR"
        report["error"] = str(e)
        print(f"  ❌ Erreur export CSV : {e}")

    return csv_filepath, report

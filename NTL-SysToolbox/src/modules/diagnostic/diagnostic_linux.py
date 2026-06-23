"""
diagnostic_linux.py
Collecte les métriques système d'une machine Linux via SSH.
Cibles NTL : WMS-DB (192.168.10.21), IPBX-VM (192.168.10.40)
"""

import paramiko
import getpass
import json
import os
from datetime import datetime


def get_ssh_password(username, host):
    """
    Récupère le mot de passe SSH :
    - D'abord depuis la variable d'environnement NTL_SSH_PASSWORD
    - Sinon, le demande à l'utilisateur (masqué)
    """
    pwd = os.getenv("NTL_SSH_PASSWORD")
    if not pwd:
        pwd = getpass.getpass(f"  Mot de passe SSH pour {username}@{host} : ")
    return pwd


def connect_ssh(host, username, password, port=22):
    """Crée et retourne une connexion SSH Paramiko."""
    client = paramiko.SSHClient()
    # AutoAddPolicy : accepte le fingerprint du serveur sans demander confirmation
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        port=port,
        username=username,
        password=password,
        timeout=10
    )
    return client


def run_command(client, command):
    """Exécute une commande à distance et retourne la sortie (stdout)."""
    stdin, stdout, stderr = client.exec_command(command)
    return stdout.read().decode("utf-8", errors="replace").strip()


def get_linux_metrics(host, username, port=22):
    """
    Se connecte en SSH à une machine Linux et collecte :
    - Nom de la machine (hostname)
    - Version de l'OS
    - Uptime
    - Usage CPU
    - Usage RAM
    - Usage disque (partition /)

    Retourne un dictionnaire avec toutes ces infos + horodatage.
    """
    print(f"\n  Connexion SSH à {host} ({username})...")
    password = get_ssh_password(username, host)

    result = {
        "timestamp": datetime.now().isoformat(),
        "target": host,
        "os_type": "Linux",
        "status": "UNKNOWN"
    }

    try:
        client = connect_ssh(host, username, password, port)
        print(f"  ✅ Connecté à {host}")

        # --- Hostname ---
        result["hostname"] = run_command(client, "hostname")

        # --- Version OS ---
        os_info = run_command(client, "cat /etc/os-release | grep PRETTY_NAME")
        # Extrait juste la valeur : PRETTY_NAME="Ubuntu 22.04.3 LTS" -> Ubuntu 22.04.3 LTS
        result["os_version"] = os_info.replace('PRETTY_NAME=', '').replace('"', '')

        # --- Uptime ---
        result["uptime"] = run_command(client, "uptime -p")

        # --- CPU (usage moyen 1 minute) ---
        load_raw = run_command(client, "cat /proc/loadavg")
        # /proc/loadavg retourne : 0.15 0.10 0.08 1/234 5678
        # On prend le 1er chiffre (charge moyenne 1 min)
        result["cpu_load_1min"] = load_raw.split()[0]

        # --- RAM ---
        mem_raw = run_command(client, "free -m | grep Mem")
        # Format : Mem:   total  used  free  shared  buff/cache  available
        parts = mem_raw.split()
        if len(parts) >= 3:
            total_ram = int(parts[1])
            used_ram = int(parts[2])
            ram_percent = round((used_ram / total_ram) * 100, 1) if total_ram > 0 else 0
            result["ram_total_mb"] = total_ram
            result["ram_used_mb"] = used_ram
            result["ram_usage_percent"] = ram_percent

        # --- Disque (partition racine /) ---
        disk_raw = run_command(client, "df -h / | tail -1")
        # Format : /dev/sda1  20G  8G  12G  40%  /
        parts = disk_raw.split()
        if len(parts) >= 5:
            result["disk_total"] = parts[1]
            result["disk_used"] = parts[2]
            result["disk_usage_percent"] = parts[4]

        result["status"] = "OK"
        client.close()

    except Exception as e:
        result["status"] = "ERREUR"
        result["error"] = str(e)
        print(f"  ❌ Erreur : {e}")

    return result


def check_mysql(host, username, port=22, mysql_user="root"):
    """
    Vérifie que MariaDB/MySQL répond sur WMS-DB via SSH.
    Retourne la version et la liste des bases de données.
    """
    print(f"\n  Vérification MariaDB/MySQL sur {host}...")
    password = get_ssh_password(username, host)

    result = {
        "timestamp": datetime.now().isoformat(),
        "target": host,
        "service": "MariaDB/MySQL",
        "status": "UNKNOWN"
    }

    try:
        client = connect_ssh(host, username, password, port)

        # Vérifie que le service mariadb/mysql tourne
        service_status = run_command(
            client,
            "systemctl is-active mariadb 2>/dev/null || systemctl is-active mysql 2>/dev/null || echo inactive"
        )
        result["service_active"] = service_status

        # Récupère la version via socket local (sans mot de passe si on est root ou si accès unix socket)
        version = run_command(
            client,
            "mysql -u root -e 'SELECT VERSION();' 2>/dev/null | tail -1 || "
            "mariadb -u root -e 'SELECT VERSION();' 2>/dev/null | tail -1 || "
            "echo 'Acces refuse - verifier les droits'"
        )
        result["version"] = version

        # Liste les bases de données disponibles
        databases = run_command(
            client,
            "mysql -u root -e 'SHOW DATABASES;' 2>/dev/null | grep -v Database || "
            "mariadb -u root -e 'SHOW DATABASES;' 2>/dev/null | grep -v Database || "
            "echo 'Non accessible'"
        )
        result["databases"] = databases.split("\n") if databases != "Non accessible" else []

        if service_status == "active":
            result["status"] = "OK"
        else:
            result["status"] = "AVERTISSEMENT"
            result["warning"] = f"Service status: {service_status}"

        client.close()

    except Exception as e:
        result["status"] = "ERREUR"
        result["error"] = str(e)
        print(f"  ❌ Erreur MySQL : {e}")

    return result

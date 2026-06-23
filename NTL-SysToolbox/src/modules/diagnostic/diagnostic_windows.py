"""
diagnostic_windows.py
Collecte les métriques système d'une machine Windows via WinRM (PowerShell distant).
Cibles NTL : DC01 (192.168.10.10), DC02 (192.168.10.11)

Prérequis sur chaque VM Windows (à faire une seule fois en PowerShell admin local) :
    Enable-PSRemoting -Force
    winrm quickconfig -q
    Set-Item WSMan:\\localhost\\Service\\Auth\\Basic -Value $true
"""

import winrm
import getpass
import os
from datetime import datetime


def get_windows_password(username, host):
    """
    Récupère le mot de passe Windows :
    - D'abord depuis la variable d'environnement NTL_ADMIN_PASSWORD
    - Sinon, le demande à l'utilisateur (masqué)
    """
    pwd = os.getenv("NTL_ADMIN_PASSWORD")
    if not pwd:
        pwd = getpass.getpass(f"  Mot de passe Windows pour {username}@{host} : ")
    return pwd


def connect_winrm(host, username, password):
    """Crée et retourne une session WinRM."""
    session = winrm.Session(
        f"http://{host}:5985/wsman",
        auth=(username, password),
        transport="ntlm",   # NTLM fonctionne pour comptes locaux et comptes de domaine
        read_timeout_sec=30,
        operation_timeout_sec=25
    )
    return session


def run_ps(session, command):
    """Exécute une commande PowerShell à distance et retourne la sortie."""
    result = session.run_ps(command)
    output = result.std_out.decode("utf-8", errors="replace").strip()
    errors = result.std_err.decode("utf-8", errors="replace").strip()
    return output, errors


def get_windows_metrics(host, username):
    """
    Se connecte en WinRM à une machine Windows Server et collecte :
    - Nom de la machine
    - Version de l'OS (édition + numéro de build)
    - Date de dernier démarrage (uptime)
    - Usage CPU (mesure ponctuelle)
    - Usage RAM
    - Usage disque (lecteur C:)

    Retourne un dictionnaire avec toutes ces infos + horodatage.
    """
    print(f"\n  Connexion WinRM à {host} ({username})...")
    password = get_windows_password(username, host)

    result = {
        "timestamp": datetime.now().isoformat(),
        "target": host,
        "os_type": "Windows",
        "status": "UNKNOWN"
    }

    try:
        session = connect_winrm(host, username, password)

        # Test de connexion basique
        out, err = run_ps(session, "hostname")
        result["hostname"] = out
        print(f"  ✅ Connecté à {host} (hostname: {out})")

        # --- Version OS ---
        out, _ = run_ps(
            session,
            "(Get-CimInstance Win32_OperatingSystem).Caption + ' - Build ' + "
            "(Get-CimInstance Win32_OperatingSystem).BuildNumber"
        )
        result["os_version"] = out

        # --- Uptime (dernier démarrage) ---
        out, _ = run_ps(
            session,
            "$os = Get-CimInstance Win32_OperatingSystem; "
            "$uptime = (Get-Date) - $os.LastBootUpTime; "
            "\"Demarrage: \" + $os.LastBootUpTime.ToString('dd/MM/yyyy HH:mm') + "
            "\" (\" + [int]$uptime.TotalHours + \"h\" + $uptime.Minutes + \"min)\""
        )
        result["uptime"] = out

        # --- CPU ---
        out, _ = run_ps(
            session,
            "$cpu = Get-CimInstance Win32_Processor | "
            "Measure-Object LoadPercentage -Average; "
            "[string]$cpu.Average + '%'"
        )
        result["cpu_usage_percent"] = out

        # --- RAM ---
        out, _ = run_ps(
            session,
            "$os = Get-CimInstance Win32_OperatingSystem; "
            "$total = [math]::Round($os.TotalVisibleMemorySize/1MB, 0); "
            "$free = [math]::Round($os.FreePhysicalMemory/1MB, 0); "
            "$used = $total - $free; "
            "$pct = [math]::Round(($used/$total)*100, 1); "
            "\"Total: ${total}GB | Utilise: ${used}GB | ${pct}%\""
        )
        result["ram_info"] = out

        # --- Disque C: ---
        out, _ = run_ps(
            session,
            "$disk = Get-PSDrive C; "
            "$used = [math]::Round($disk.Used/1GB, 1); "
            "$free = [math]::Round($disk.Free/1GB, 1); "
            "$total = $used + $free; "
            "$pct = [math]::Round(($used/$total)*100, 1); "
            "\"Total: ${total}GB | Utilise: ${used}GB | ${pct}%\""
        )
        result["disk_C"] = out

        result["status"] = "OK"

    except Exception as e:
        result["status"] = "ERREUR"
        result["error"] = str(e)
        print(f"  ❌ Erreur WinRM : {e}")
        print("  → Vérifiez que Enable-PSRemoting a été exécuté sur la VM")

    return result


def check_ad_dns(host, username):
    """
    Vérifie l'état d'Active Directory et DNS sur un contrôleur de domaine
    via WinRM/PowerShell.
    """
    print(f"\n  Vérification AD/DNS sur {host}...")
    password = get_windows_password(username, host)

    result = {
        "timestamp": datetime.now().isoformat(),
        "target": host,
        "service": "AD/DNS",
        "status": "UNKNOWN"
    }

    try:
        session = connect_winrm(host, username, password)

        # --- État du service Active Directory ---
        out, _ = run_ps(
            session,
            "(Get-Service NTDS).Status"
        )
        result["ad_service_status"] = out

        # --- État du service DNS ---
        out, _ = run_ps(
            session,
            "(Get-Service DNS).Status"
        )
        result["dns_service_status"] = out

        # --- Nom du domaine ---
        out, _ = run_ps(
            session,
            "(Get-ADDomain).DNSRoot"
        )
        result["domain_name"] = out

        # --- Nombre d'utilisateurs actifs ---
        out, _ = run_ps(
            session,
            "(Get-ADUser -Filter {Enabled -eq $true} | Measure-Object).Count"
        )
        result["active_users_count"] = out

        # --- Contrôleurs de domaine du domaine ---
        out, _ = run_ps(
            session,
            "(Get-ADDomainController -Filter *).Name -join ', '"
        )
        result["domain_controllers"] = out

        # --- Test de résolution DNS ---
        out, _ = run_ps(
            session,
            "Resolve-DnsName localhost -ErrorAction SilentlyContinue | "
            "Select-Object -First 1 -ExpandProperty IPAddress"
        )
        result["dns_resolution_test"] = "OK" if out else "ECHEC"

        if result["ad_service_status"] == "Running" and result["dns_service_status"] == "Running":
            result["status"] = "OK"
        else:
            result["status"] = "AVERTISSEMENT"

    except Exception as e:
        result["status"] = "ERREUR"
        result["error"] = str(e)
        print(f"  ❌ Erreur AD/DNS : {e}")

    return result

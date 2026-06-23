# NTL-SysToolbox

Outil en ligne de commande développé pour **NordTransit Logistics (NTL)**.  
Il industrialise les vérifications d'exploitation, sécurise la gestion des sauvegardes de la base métier et produit un audit d'obsolescence.

> Projet réalisé dans le cadre du BLOC E6.1 – Concevoir et tester des solutions applicatives  
> Bachelor 3 ASRBD – EPSI – Année 2025/2026  
> Auteur : ADEOSSI Nana Aïchatou

---

## Prérequis

- Python 3.10 ou supérieur
- Accès réseau aux VMs NTL (192.168.10.0/24)
- WinRM activé sur DC01 et DC02
- SSH activé sur WMS-DB et IPBX-VM

---

## Installation

```bash
# 1. Cloner le dépôt
git clone https://github.com/<votre-repo>/NTL-SysToolbox.git
cd NTL-SysToolbox

# 2. Créer l'environnement virtuel
python -m venv .venv

# 3. Activer l'environnement (Windows)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1

# 4. Installer les dépendances
pip install paramiko pywinrm
```

---

## Lancement

```bash
python main.py
```

Le menu interactif s'affiche :

```
═══════════════════════════════════════════════
       NTL-SysToolbox v1.0
       NordTransit Logistics - Siège Lille
═══════════════════════════════════════════════

  1. Diagnostic système (DC01/DC02/WMS-DB)
  2. Sauvegarde WMS (dump SQL)
  3. Export CSV d'une table WMS
  4. Audit d'obsolescence du réseau
  5. Quitter
```

---

## Configuration

Le fichier `config/config.json` contient :
- Les adresses IP des serveurs cibles
- Les noms d'utilisateurs de connexion
- Les plages réseau pour l'audit
- Les paramètres de la base MariaDB

Les mots de passe ne sont **jamais stockés** dans ce fichier.  
Ils sont demandés à l'exécution ou chargés depuis des variables d'environnement :

```bash
# Optionnel - évite de retaper les mots de passe
set NTL_SSH_PASSWORD=votre_mot_de_passe_ssh
set NTL_ADMIN_PASSWORD=votre_mot_de_passe_windows
```

---

## Modules

### 1. Diagnostic système
Se connecte à DC01/DC02 via WinRM et à WMS-DB via SSH.  
Vérifie : état AD/DNS, version OS, uptime, CPU, RAM, disque, MariaDB.  
Produit un rapport JSON horodaté dans `outputs/reports/`.

### 2. Sauvegarde WMS (SQL)
Exécute un `mysqldump` complet de la base WMS sur WMS-DB via SSH.  
Rapatrie le fichier `.sql` localement avec un rapport de traçabilité JSON.

### 3. Export CSV
Exporte une table MariaDB au format CSV via SSH.  
Le nom de la table est demandé interactivement.

### 4. Audit d'obsolescence
Scanne le réseau `192.168.10.0/24`, détecte les hôtes actifs et leurs OS.  
Compare avec la base EOL (`config/eol_database.json`).  
Produit un rapport JSON + CSV classé par statut de support.

---

## Structure du projet

```
NTL-SysToolbox/
├── main.py                          # Point d'entrée - menu interactif
├── requirements.txt                 # Dépendances Python
├── config/
│   ├── config.json                  # Configuration des serveurs
│   └── eol_database.json            # Base des fins de vie OS
├── src/
│   └── modules/
│       ├── diagnostic/
│       │   ├── diagnostic_linux.py  # Métriques SSH + MariaDB
│       │   └── diagnostic_windows.py# Métriques WinRM + AD/DNS
│       ├── backup/
│       │   └── backup.py            # Dump SQL + export CSV
│       └── audit/
│           └── audit.py             # Scan réseau + rapport EOL
└── outputs/
    ├── logs/                        # Logs d'exécution
    └── reports/                     # Rapports JSON, CSV, SQL générés
```

---

## Infrastructure NTL ciblée

| Serveur   | IP             | OS                    | Rôle                        |
|-----------|----------------|-----------------------|-----------------------------|
| DC01      | 192.168.10.10  | Windows Server 2022   | Contrôleur de domaine principal (AD/DNS) |
| DC02      | 192.168.10.11  | Windows Server 2022   | Contrôleur de domaine secondaire |
| WMS-DB    | 192.168.10.21  | Ubuntu 22.04          | Base MariaDB du WMS         |
| IPBX-VM   | 192.168.10.40  | Ubuntu 22.04          | Serveur IPBX (téléphonie)   |

---

## Sorties produites

Tous les fichiers sont générés dans `outputs/reports/` avec horodatage :

| Fichier | Description |
|---------|-------------|
| `diagnostic_report_YYYYMMDD_HHMMSS.json` | Rapport complet de diagnostic |
| `backup_wms_YYYYMMDD_HHMMSS.sql` | Dump SQL de la base WMS |
| `backup_report_YYYYMMDD_HHMMSS.json` | Rapport de traçabilité de la sauvegarde |
| `export_<table>_YYYYMMDD_HHMMSS.csv` | Export CSV d'une table |
| `audit_report_YYYYMMDD_HHMMSS.json` | Rapport d'audit d'obsolescence |
| `audit_report_YYYYMMDD_HHMMSS.csv` | Rapport d'audit au format tableur |

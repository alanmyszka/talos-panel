# Talos Panel

Talos Panel is a self-hosted web panel for installing and managing Minecraft Java Edition
servers. It uses the **itzg/minecraft-server** Docker image, runs on Docker, and provides an English and
Polish interface.

## Features

### Server creation and installation
<img width="1920" height="1080" alt="obraz" src="https://github.com/user-attachments/assets/0895f530-b398-4900-ac51-a552981fadb7" />

- create Vanilla, Paper, Purpur, Pufferfish, Fabric, Quilt, Forge and NeoForge servers;
- select an available Minecraft version;
- configure the server name, port, and memory;
- configure initial gameplay settings;
- optionally enable Aikar flags or provide custom JVM flags;
- let the ITZG image prepare the selected distribution on first start;
- automatically select the required Java version.

### Server management
<img width="1920" height="1080" alt="obraz" src="https://github.com/user-attachments/assets/cb9a7ffd-55c2-461b-a83d-885222e1e7cd" />

- view all accessible servers from one dashboard;
- see server status, address, software version, player count, and uptime;
- start, stop, and restart servers;
- copy the server address;
- delete a server with confirmation;
- optionally restart a server after a crash.

### Live console
<img width="1920" height="1080" alt="obraz" src="https://github.com/user-attachments/assets/7b861afd-b4a3-4ea3-b19c-279f98ebdd1c" />

- view live Minecraft server output;
- send commands directly from the browser;
- use commands with or without a leading `/`;
- inspect recent server messages and errors.

### Player management
<img width="1920" height="1080" alt="obraz" src="https://github.com/user-attachments/assets/3a974163-d8b9-4830-a2a5-f541a70bc970" />

- view online and known offline players;
- see player avatars, nicknames, UUIDs, last activity, and play time;
- check OP, whitelist, and ban status;
- kick and ban players;
- pardon banned players;
- add and remove players from the whitelist;
- grant and revoke operator permissions.

### File manager
<img width="1920" height="1080" alt="obraz" src="https://github.com/user-attachments/assets/c8e683ee-1378-48f3-9eac-aae8954f5a9f" />

- browse server files and directories;
- upload files and complete folders;
- use drag and drop uploads;
- download files and directories;
- create directories;
- rename, move, and copy files or folders;
- edit supported text files;
- extract ZIP archives;
- delete files and directories;
- enable and disable plugin JARs on Paper-compatible servers.

### Server settings
<img width="1920" height="1080" alt="obraz" src="https://github.com/user-attachments/assets/38dc7ef4-fda6-44a2-b1a2-6012dad628ab" />

- edit MOTD;
- change game mode and difficulty;
- configure the maximum player count;
- enable or disable whitelist, PvP, and flight;
- configure view and simulation distance;
- change the server port and memory allocation;
- update JVM startup options.

### Backups
<img width="1920" height="1080" alt="obraz" src="https://github.com/user-attachments/assets/7f80d626-c802-4241-ad70-6141302fb6db" />

- create manual backups;
- enable automatic backups;
- configure backup frequency and retention;
- download and delete backups;
- restore a server from a selected backup;
- view available disk space and backup history.

### Server updates
<img width="1920" height="1080" alt="obraz" src="https://github.com/user-attachments/assets/98df6833-da86-4e2f-9050-74747eec034e" />

- check available Minecraft versions for each supported server type;
- update a server to a selected version;
- create a recovery backup before updating;
- view update history;
- roll back an update.

### Monitoring
<img width="1920" height="1080" alt="obraz" src="https://github.com/user-attachments/assets/a4ba2ba5-3a87-4d9d-a8ca-cb76d29a925d" />

- view current CPU and memory usage;
- see player-count history;
- inspect uptime and runtime state;
- view historical charts and runtime events.

### Users and access
<img width="1920" height="1080" alt="obraz" src="https://github.com/user-attachments/assets/41701a5d-ea8e-4170-90f5-e46819eddb26" />
<img width="1920" height="1080" alt="obraz" src="https://github.com/user-attachments/assets/b1ff41f2-6428-4fee-be81-ba5a198a4b5e" />
<img width="1920" height="1080" alt="obraz" src="https://github.com/user-attachments/assets/3ddb8f42-c93f-4688-b86d-ddaaa3fb4cdc" />

- create administrator and user accounts;
- enable or disable account login;
- revoke active sessions;
- delete user accounts;
- assign owner or operator access to individual servers;
- review which servers each user can access;
- change account passwords;
- enable optional two-factor authentication.

### Administration
<img width="1920" height="1080" alt="obraz" src="https://github.com/user-attachments/assets/55fcf2f0-e04a-4ba0-ba7b-aa328f34d4fc" />
<img width="1920" height="1080" alt="obraz" src="https://github.com/user-attachments/assets/c737b717-8b97-49f4-9d1b-ca15249504d0" />

- review panel and server activity in the audit log;
- filter audit events by action, user, server, IP address, details, and date;
- review account and environment information in Security Review;
- switch the interface between English and Polish.

## Requirements

- Linux or WSL 2;
- Docker Engine or Docker Desktop;
- Docker Compose;
- Git.

On Windows, enable Docker Desktop integration for the WSL distribution where the project
will be installed.

## Installation

Clone the repository:

```bash
git clone https://github.com/alanmyszka/talos-panel.git
cd talos-panel
```

Create the environment file:

```bash
cp .env.example .env
```

Before starting the panel, edit `.env` and:

- replace `change-me` with a strong PostgreSQL password;
- set `BASE_DIR` to the absolute path of the cloned repository.

You can print the current path with:

```bash
pwd
```

Example configuration:

```dotenv
POSTGRES_DB=talos_panel
POSTGRES_USER=talos_panel
POSTGRES_PASSWORD=replace-with-a-strong-password
BASE_DIR=/home/your-user/talos-panel
SECURE_COOKIES=false
```

Build and start the application:

```bash
docker compose up -d --build
```

Open the panel at:

```text
http://localhost:8000
```

The first visit opens the setup page. Create the initial administrator account, sign in,
and use **New server** to install the first Minecraft server.

## Common commands

Check service status:

```bash
docker compose ps
```

View panel logs:

```bash
docker compose logs -f panel
```

Rebuild the panel after pulling or changing the code:

```bash
docker compose up -d --build panel
```

Stop the panel without deleting its data:

```bash
docker compose down
```

Start it again:

```bash
docker compose up -d
```

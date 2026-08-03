# Talos Panel

Talos Panel is a self-hosted web panel for installing and managing Minecraft Java Edition
servers. It supports **Paper** and **Vanilla**, runs on Docker, and provides an English and
Polish interface.

## Features

### Server creation and installation

- create Paper and Vanilla servers from the web interface;
- select an available Minecraft version;
- configure the server name, port, and memory;
- configure initial gameplay settings;
- optionally enable Aikar flags or provide custom JVM flags;
- follow installation progress and see installation errors;
- automatically select the required Java version.

### Server management

- view all accessible servers from one dashboard;
- see server status, address, software version, player count, and uptime;
- start, stop, and restart servers;
- copy the server address;
- delete a server with confirmation;
- optionally restart a server after a crash.

### Live console

- view live Minecraft server output;
- send commands directly from the browser;
- use commands with or without a leading `/`;
- inspect recent server messages and errors.

### Player management

- view online and known offline players;
- see player avatars, nicknames, UUIDs, last activity, and play time;
- check OP, whitelist, and ban status;
- kick and ban players;
- pardon banned players;
- add and remove players from the whitelist;
- grant and revoke operator permissions.

### File manager

- browse server files and directories;
- upload files and complete folders;
- use drag and drop uploads;
- download files and directories;
- create directories;
- rename, move, and copy files or folders;
- edit supported text files;
- extract ZIP archives;
- delete files and directories;
- enable and disable Paper plugin JARs.

### Server settings

- edit MOTD;
- change game mode and difficulty;
- configure the maximum player count;
- enable or disable whitelist, PvP, and flight;
- configure view and simulation distance;
- change the server port and memory allocation;
- update JVM startup options.

### Backups

- create manual backups;
- enable automatic backups;
- configure backup frequency and retention;
- download and delete backups;
- restore a server from a selected backup;
- view available disk space and backup history.

### Server updates

- check available Paper and Vanilla versions;
- update a server to a selected version;
- create a recovery backup before updating;
- view update history;
- roll back an update.

### Monitoring

- view current CPU and memory usage;
- see player-count history;
- inspect uptime and runtime state;
- view historical charts and runtime events.

### Users and access

- create administrator and user accounts;
- enable or disable account login;
- revoke active sessions;
- delete user accounts;
- assign owner or operator access to individual servers;
- review which servers each user can access;
- change account passwords;
- enable optional two-factor authentication.

### Administration

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

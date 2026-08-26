# Техническое описание проекта: Self-Hosted VPN Gateway Manager

## 1. Общая идея проекта

Необходимо разработать self-hosted WEB-панель для развёртывания, настройки и дальнейшего обслуживания централизованного VPN-шлюза на Linux.

Основная задача проекта — убрать необходимость вручную:

- устанавливать и обновлять VPN/proxy-ядро;
- настраивать Linux как сетевой шлюз;
- включать IP forwarding;
- писать nftables/iptables правила;
- вручную редактировать конфиги Mihomo;
- конвертировать VLESS-ссылки и подписки;
- добавлять proxy nodes;
- создавать proxy groups;
- прописывать routing rules;
- следить за системными сервисами;
- восстанавливать конфигурацию после обновлений;
- помнить, что и где было изменено вручную.

Пользователь должен иметь возможность развернуть чистую Linux VM, установить на неё данный менеджер и после этого выполнить всю основную настройку через WEB-интерфейс.

Проект не должен пытаться заменить Zashboard.

Zashboard необходимо использовать как отдельный готовый runtime dashboard для Mihomo.

Ответственность собственной панели:

- установка;
- bootstrap;
- системная сеть;
- subscriptions;
- proxy nodes;
- proxy groups;
- routing;
- генерация конфигурации;
- health checks;
- backup/restore;
- обновления;
- диагностика.

Ответственность Zashboard:

- активные соединения;
- realtime traffic;
- runtime proxy switching;
- latency;
- proxy groups runtime view;
- logs;
- connection history;
- topology;
- другие runtime-возможности, которые Zashboard уже умеет и продолжает развивать.

Архитектурно:

```text
                    VPN Gateway Manager
               ┌────────────────────────┐
               │ WEB UI                 │
               │                        │
               │ Installation           │
               │ System Networking      │
               │ Nodes                  │
               │ Subscriptions          │
               │ Proxy Groups           │
               │ Routing Builder        │
               │ Config Compiler        │
               │ Health / Backup        │
               │ Updates                │
               └────────────┬───────────┘
                            │
                            ▼
                       Internal DB
                            │
                            ▼
                    Config Compiler
                            │
                            ▼
                       config.yaml
                            │
                            ▼
                          Mihomo
                            │
                     REST / WebSocket
                            │
                            ▼
                        Zashboard
```

---

# 2. Основной принцип архитектуры

## 2.1. Конфиг Mihomo не должен быть Source of Truth

Нельзя строить систему вокруг прямого редактирования `config.yaml`.

Основной источник данных должен быть собственной внутренней моделью в БД.

Например:

```text
Nodes
Subscriptions
Proxy Groups
Routing Rules
System Settings
DNS Settings
Gateway Settings
Profiles
```

А уже на основании этих сущностей необходимо генерировать `config.yaml`.

Схема:

```text
WEB UI
   ↓
Internal API
   ↓
Database
   ↓
Config Compiler
   ↓
config.yaml
   ↓
mihomo -t
   ↓
apply
   ↓
restart/reload
```

Это позволит в будущем поддержать другие backend/core без полной переделки UI.

Например:

```text
Internal Model
      │
      ├── MihomoCompiler
      │       ↓
      │   config.yaml
      │
      └── SingBoxCompiler
              ↓
          config.json
```

На первом этапе необходимо реализовать только Mihomo.

---

# 3. Целевой пользовательский сценарий

Есть новая Linux VM.

Предполагается условно:

```text
Ubuntu / Debian
1–2 сетевых интерфейса
чистая система
```

Пользователь устанавливает VPN Gateway Manager одной командой.

Например:

```bash
curl -fsSL https://example/install.sh | bash
```

После установки открывает:

```text
http://<VM-IP>:8080
```

И получает мастер первичной настройки.

Пример:

```text
VPN Gateway Setup

LAN Interface:
[ ens18 ]

WAN Interface:
[ ens19 ]

Gateway mode:
[ ON ]

Proxy Core:
[ Mihomo ]

Traffic mode:
[ TUN ]

DNS:
[ System / Custom ]

[ Deploy ]
```

После нажатия `Deploy` система должна автоматически:

```text
1. проверить окружение;
2. определить Linux distribution;
3. проверить root/sudo;
4. определить interfaces;
5. установить Mihomo;
6. создать системного пользователя;
7. создать каталоги;
8. установить systemd service;
9. включить IP forwarding;
10. настроить сетевые параметры;
11. создать nftables rules;
12. подготовить routing;
13. создать базовый Mihomo config;
14. проверить config через mihomo -t;
15. запустить Mihomo;
16. установить Zashboard;
17. настроить external-controller;
18. проверить API Mihomo;
19. проверить доступность Zashboard;
20. показать итоговый статус.
```

В результате пользователь должен получить:

```text
✓ Mihomo installed
✓ Mihomo running
✓ Config valid
✓ IP forwarding enabled
✓ Gateway routing configured
✓ Firewall configured
✓ Zashboard installed
✓ Zashboard available
✓ API available
```

---

# 4. Основные модули системы

## 4.1. Installation / Bootstrap

Необходимо реализовать модуль первоначального развёртывания.

Он должен уметь:

- определять ОС;
- проверять архитектуру CPU;
- устанавливать зависимости;
- скачивать Mihomo;
- проверять checksum;
- устанавливать binary;
- создавать config directories;
- создавать systemd unit;
- создавать пользователя сервиса;
- настраивать автозапуск;
- устанавливать Zashboard;
- создавать backup перед изменениями;
- выполнять health check после установки.

Нужно предусмотреть повторный запуск installer без повреждения существующей установки.

То есть операции должны быть по возможности idempotent.

---

# 5. System Networking

Это один из ключевых модулей.

Панель должна управлять системными настройками Linux, необходимыми для работы машины как gateway.

Необходимо поддержать:

- LAN interface;
- WAN interface;
- IPv4 forwarding;
- при необходимости IPv6 forwarding;
- nftables;
- routing tables;
- policy routing;
- TUN mode;
- TProxy mode — позже, если потребуется;
- DNS handling;
- исключения локальных сетей;
- bypass для loopback;
- bypass для самого gateway;
- bypass для RFC1918 там, где нужно.

Пользователь не должен руками редактировать:

```text
/etc/sysctl.conf
/etc/nftables.conf
ip rule
ip route
systemd units
```

WEB UI должен предоставлять понятную форму.

Пример:

```text
System Networking

LAN interface:
ens18

WAN interface:
ens19

IPv4 forwarding:
ON

Traffic interception:
● TUN
○ TProxy

Local networks:
192.168.1.0/24
10.0.0.0/8

Bypass local:
ON

[ Apply ]
```

Перед применением необходимо:

```text
generate
validate
backup
apply
verify
```

При ошибке — rollback.

---

# 6. Nodes

Нужен полноценный менеджер прокси-узлов.

Минимально необходимо поддержать:

- VLESS;
- Hysteria2;
- Trojan — опционально;
- Shadowsocks — опционально;
- другие протоколы можно добавлять позже.

Node должен существовать как нормальная сущность в БД.

Пример модели:

```json
{
  "id": 15,
  "name": "DE-01",
  "enabled": true,
  "protocol": "vless",
  "server": "example.com",
  "port": 443,
  "uuid": "...",
  "transport": "xhttp",
  "security": "reality",
  "sni": "www.microsoft.com",
  "fingerprint": "chrome",
  "public_key": "...",
  "short_id": "...",
  "source": "manual"
}
```

Необходимо позволить:

- создавать node вручную;
- редактировать;
- удалять;
- disable/enable;
- тестировать;
- клонировать;
- давать понятное имя;
- видеть источник node.

---

# 7. Импорт VLESS-ссылок

Это одна из обязательных функций.

Пользователь вставляет:

```text
vless://...
```

Панель должна:

```text
parse URI
      ↓
validate
      ↓
extract params
      ↓
create internal Node
      ↓
show preview
      ↓
save
```

Необходимо учитывать:

- UUID;
- host;
- port;
- encryption;
- flow;
- security;
- SNI;
- fingerprint;
- pbk;
- sid;
- path;
- host header;
- transport;
- type;
- xhttp;
- grpc;
- ws;
- tcp;
- reality;
- TLS.

Пользователь не должен самостоятельно переводить VLESS URI в YAML.

---

# 8. Subscriptions

Необходимо реализовать Subscription Manager.

Пользователь должен иметь возможность добавить URL подписки:

```text
Name:
My provider

URL:
https://provider.example/sub/...
```

Система должна:

```text
download subscription
        ↓
detect format
        ↓
parse nodes
        ↓
normalize
        ↓
show changes
        ↓
update DB
```

Необходимо поддержать минимум:

- URI list;
- Base64 URI subscriptions;
- Clash/Mihomo YAML subscriptions;
- обычные VLESS URI.

В будущем возможно добавить sing-box subscriptions.

Для подписки хранить:

```text
id
name
url
enabled
last_update
last_success
last_error
update_interval
nodes_count
```

Нужна кнопка:

```text
Update now
```

И возможность настроить автоматическое обновление.

Очень важно корректно обрабатывать обновления.

Нельзя просто удалять все старые nodes.

Нужно пытаться сопоставлять существующие nodes с новыми по стабильному fingerprint.

Например:

```text
protocol
server
port
UUID
transport
```

Чтобы сохранять:

- custom name;
- group membership;
- пользовательские настройки.

---

# 9. Proxy Groups

Нужен визуальный менеджер Proxy Groups.

Пример:

```text
VPN-Europe

Type:
● select
○ url-test
○ fallback

Nodes:
✓ DE-01
✓ DE-02
✓ NL-01
□ US-01

Health URL:
https://www.gstatic.com/generate_204

Interval:
300

[ Save ]
```

Необходимо поддержать как минимум:

```text
select
url-test
fallback
load-balance — позже
```

Proxy Group — отдельная сущность в БД.

Например:

```text
id
name
type
nodes
providers
health_url
interval
tolerance
enabled
```

---

# 10. Routing Builder

Это один из самых важных компонентов.

Необходимо полностью избавиться от необходимости вручную писать:

```yaml
rules:
```

Пользователь должен создавать правила через UI.

Пример формы:

```text
Add Routing Rule

Match type:
[ Domain suffix ]

Value:
example.com

Destination:
[ VPN-Europe ]

Enabled:
ON

[ Save ]
```

Поддержать минимум:

```text
DOMAIN
DOMAIN-SUFFIX
DOMAIN-KEYWORD
IP-CIDR
IP-CIDR6
SRC-IP-CIDR
DST-PORT
SRC-PORT
NETWORK
RULE-SET
GEOIP
GEOSITE — если используется
MATCH
```

Правила должны иметь:

```text
priority/order
enabled
name
comment
type
value
target
source
```

Например:

```text
10  Local networks        → DIRECT
20  YouTube               → VPN-Europe
30  Telegram              → VPN-Europe
40  OpenAI                → VPN-Europe
50  example.com           → VPN-Europe
999 Everything else       → DIRECT
```

Необходимо позволить менять порядок drag-and-drop.

Поскольку порядок routing rules критичен, UI должен явно это показывать.

---

# 11. Rule Sets

Необходимо поддержать централизованные rule-set источники.

Пример:

```text
Telegram
YouTube
Discord
OpenAI
Meta
WhatsApp
```

RuleSet должен быть отдельной сущностью.

Поля:

```text
name
source_url
format
behavior
update_interval
last_update
checksum
enabled
```

При этом UI должен явно показывать, что автоматическое обновление rule-set не гарантирует корректность данных.

Нужно иметь возможность:

- использовать remote URL;
- использовать локальный файл;
- обновить вручную;
- посмотреть дату последнего обновления;
- посмотреть количество правил;
- временно отключить;
- заменить источник.

---

# 12. Profiles

Нужна сущность `Profile`.

Это позволит разворачивать готовые наборы настроек.

Пример:

```text
Home Gateway

System:
TUN
LAN: auto
DIRECT local networks

Groups:
VPN-Europe
VPN-US

Rules:
Telegram → VPN-Europe
YouTube → VPN-Europe
Discord → VPN-Europe
OpenAI → VPN-Europe
Meta → VPN-Europe
Default → DIRECT
```

Другой профиль:

```text
Friend Gateway

Telegram → VPN
YouTube → VPN
Discord → VPN
Default → DIRECT
```

При развёртывании новой VM можно выбрать профиль.

Это важно для сценария установки человеку, который не разбирается в Linux.

---

# 13. Config Compiler

Необходимо создать отдельный модуль генерации Mihomo YAML.

Он получает данные из DB:

```text
System Settings
Nodes
Subscriptions
Proxy Groups
Rule Providers
Rules
DNS Settings
```

и собирает валидный:

```text
config.yaml
```

Config Compiler не должен находиться внутри UI-логики.

Это отдельный backend service/module.

После генерации:

```text
write temporary config
        ↓
mihomo -t -f temp.yaml
        ↓
if valid:
    backup old config
    replace config
    reload/restart
else:
    reject changes
```

Никогда не применять непроверенный config.

---

# 14. Transaction / Rollback

Любая критичная операция должна иметь безопасную схему:

```text
Current state
    ↓
Backup
    ↓
Generate
    ↓
Validate
    ↓
Apply
    ↓
Health check
    ↓
Success
```

Если:

```text
health check failed
```

то:

```text
rollback config
rollback networking
restart previous service
```

Особенно это касается:

- Mihomo config;
- nftables;
- sysctl;
- routing;
- core update.

---

# 15. Zashboard Integration

Необходимо использовать Zashboard как готовый runtime UI.

Не нужно форкать Zashboard.

Не нужно копировать его runtime-функции.

VPN Gateway Manager должен:

```text
download latest supported Zashboard release
install static build
configure external-ui
configure Mihomo external-controller
verify connection
```

В основном UI нужна вкладка:

```text
Live Dashboard
```

которая:

- либо открывает Zashboard;
- либо встраивает его, если это технически удобно;
- либо открывает во внутреннем маршруте `/dashboard`.

Необходимо избегать глубокой зависимости от внутренних компонентов Zashboard.

Главная зависимость — стандартный runtime API Mihomo.

---

# 16. Updates

Нужен отдельный Update Manager.

Минимально:

```text
VPN Gateway Manager
Mihomo
Zashboard
```

UI:

```text
Component              Installed       Latest

Gateway Manager        0.1.0           0.1.0
Mihomo                 1.19.8          1.20.1
Zashboard              3.21.0          3.22.0
```

Для каждого:

```text
[ Update ]
```

Перед обновлением:

```text
backup
download
checksum
replace
restart
health check
rollback if failed
```

---

# 17. Health Dashboard

Главная страница должна показывать реальное состояние системы.

Например:

```text
System
────────────────────
Linux            ✓
IP forwarding    ✓
nftables         ✓
TUN              ✓
DNS              ✓

Mihomo
────────────────────
Installed        ✓
Running          ✓
Config valid     ✓
API              ✓
Version          1.x.x

Proxy
────────────────────
Nodes            7
Healthy          5
Failed           2

Subscriptions
────────────────────
Provider A       ✓ 12 min ago
Provider B       ✗ auth failed

Zashboard
────────────────────
Installed        ✓
Available        ✓
Version          3.x.x
```

---

# 18. Desired State

Необходимо по возможности уйти от модели:

```text
button → execute shell command
```

к модели desired state.

Например:

```json
{
  "mihomo": {
    "installed": true,
    "enabled": true
  },
  "network": {
    "ipv4_forward": true,
    "mode": "tun"
  },
  "zashboard": {
    "installed": true
  }
}
```

Система сравнивает:

```text
Desired State
vs
Actual State
```

и показывает drift.

Например:

```text
Mihomo running        OK
IP forwarding         OK
nftables rules        DRIFT
Zashboard version     OUTDATED
Config checksum       MODIFIED
```

С кнопкой:

```text
Repair
```

---

# 19. Backup / Restore

Необходимо поддержать резервные копии.

Backup должен включать:

```text
database
generated config
system settings relevant to project
network config
nftables rules
application settings
subscription metadata
```

UI:

```text
Backups

23.08.2026 22:10    Before Mihomo update
20.08.2026 15:02    Before routing change
18.08.2026 01:44    Manual backup
```

Кнопки:

```text
Restore
Download
Delete
```

---

# 20. Audit Log

Очень важно хранить историю изменений.

Это решает проблему:

> «Я не помню, что правил неделю назад».

Audit Log:

```text
23.08.2026 22:41
Added routing rule
example.com → VPN-Europe

23.08.2026 22:34
Subscription updated
Provider-DE
4 nodes added
1 removed

22.08.2026 11:20
Changed proxy group
VPN-Europe
fallback → url-test
```

Хранить:

```text
timestamp
user
action
entity
before
after
result
```

---

# 21. Security

Минимально:

- локальная авторизация;
- password hashing;
- session timeout;
- CSRF protection;
- API auth;
- secrets не писать в обычные логи;
- subscription URLs считать секретными;
- UUID/private keys/credentials маскировать;
- bind панели по умолчанию либо LAN, либо localhost;
- предупреждать при публикации наружу;
- сделать backup permissions безопасными.

---

# 22. Рекомендуемый стек

Это не жёсткое требование.

Возможный backend:

```text
Python
FastAPI
SQLAlchemy
SQLite
Pydantic
systemd
nftables
```

Frontend:

```text
Vue 3
TypeScript
Vite
```

Либо React.

Для данного проекта Vue может быть удобен из-за большого количества форм и dashboard UI.

БД на первом этапе:

```text
SQLite
```

Этого достаточно.

---

# 23. Пример структуры backend

```text
backend/
├── api/
│   ├── nodes.py
│   ├── subscriptions.py
│   ├── routing.py
│   ├── proxy_groups.py
│   ├── system.py
│   ├── health.py
│   ├── updates.py
│   └── backups.py
│
├── models/
│   ├── node.py
│   ├── subscription.py
│   ├── routing_rule.py
│   ├── proxy_group.py
│   └── settings.py
│
├── services/
│   ├── mihomo/
│   │   ├── installer.py
│   │   ├── compiler.py
│   │   ├── validator.py
│   │   ├── runtime.py
│   │   └── updater.py
│   │
│   ├── networking/
│   │   ├── sysctl.py
│   │   ├── nftables.py
│   │   ├── routes.py
│   │   └── interfaces.py
│   │
│   ├── subscriptions/
│   │   ├── parser.py
│   │   └── updater.py
│   │
│   ├── zashboard/
│   │   ├── installer.py
│   │   └── updater.py
│   │
│   ├── backup.py
│   └── health.py
│
└── main.py
```

---

# 24. Пример структуры frontend

```text
frontend/
├── pages/
│   ├── Overview.vue
│   ├── Setup.vue
│   ├── Nodes.vue
│   ├── Subscriptions.vue
│   ├── ProxyGroups.vue
│   ├── Routing.vue
│   ├── System.vue
│   ├── Backups.vue
│   ├── Updates.vue
│   └── Dashboard.vue
│
├── components/
│   ├── NodeEditor.vue
│   ├── SubscriptionEditor.vue
│   ├── RuleEditor.vue
│   ├── ProxyGroupEditor.vue
│   ├── HealthCard.vue
│   └── InterfaceSelector.vue
│
└── api/
```

---

# 25. MVP

Первую версию не нужно перегружать.

## MVP должен уметь:

1. Установить Mihomo.
2. Установить Zashboard.
3. Создать systemd service.
4. Включить IP forwarding.
5. Настроить TUN gateway.
6. Настроить nftables.
7. Добавить VLESS node по URI.
8. Добавить subscription.
9. Создать proxy group.
10. Создать routing rule через UI.
11. Сгенерировать config.yaml.
12. Проверить config через `mihomo -t`.
13. Применить config.
14. Показать health status.
15. Открыть Zashboard.
16. Создать backup.
17. Показать audit log.

Не нужно в MVP:

```text
multi-core
sing-box
Xray
cluster
multi-user RBAC
Kubernetes
HA
distributed agents
complex monitoring
```

---

# 26. Приоритет разработки

Рекомендуемый порядок:

```text
Phase 1
Database + API + Mihomo config compiler

Phase 2
VLESS parser + Nodes

Phase 3
Proxy Groups + Routing Builder

Phase 4
System networking + gateway mode

Phase 5
Mihomo installer + systemd

Phase 6
Zashboard integration

Phase 7
Subscriptions

Phase 8
Health checks

Phase 9
Backup / Restore

Phase 10
Updater + Audit Log

Phase 11
Profiles / Desired State
```

---

# 27. Ключевые ограничения

1. Не делать собственную замену Zashboard.
2. Не использовать Mihomo YAML как основную БД.
3. Не применять конфиг без `mihomo -t`.
4. Не применять networking без возможности rollback.
5. Не удалять существующие subscription nodes без предварительного diff.
6. Не хранить secrets в логах.
7. Не привязывать frontend к синтаксису Mihomo.
8. Внутренняя модель должна быть независима от конкретного core.
9. На первом этапе поддерживается только Mihomo.
10. Все system changes должны быть максимально idempotent.

---

# 28. Главная конечная цель

Необходимо получить продукт, который превращает обычную чистую Linux VM в управляемый VPN gateway.

Пользовательский опыт должен быть максимально близок к:

```text
Install Manager
      ↓
Open Web UI
      ↓
Select interfaces
      ↓
Deploy Gateway
      ↓
Add subscription
      ↓
Create routing rules
      ↓
Done
```

Вместо текущего процесса:

```text
SSH
↓
install packages
↓
download core
↓
write config
↓
parse VLESS manually
↓
edit YAML
↓
sysctl
↓
nftables
↓
ip rules
↓
systemd
↓
restart
↓
debug
↓
edit YAML again
↓
forget what was changed
```

Именно автоматизация этого жизненного цикла является главной ценностью проекта.
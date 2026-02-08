# 🚀 Развертывание бота в продакшене (Nginx + Systemd)

Подробная инструкция по развертыванию Telegram бота на VPS с использованием Nginx и Systemd.

**Домен для production:** `bot.cryptoshop.pro`

**Режим работы:** Webhook (рекомендуется для production)

---

## 📋 Содержание

- [Требования](#-требования)
- [Архитектура](#-архитектура)
- [Подготовка сервера](#-подготовка-сервера)
- [Развертывание кода](#-развертывание-кода)
- [Настройка Systemd](#-настройка-systemd)
- [Настройка Nginx](#-настройка-nginx)
- [Установка SSL сертификата](#-установка-ssl-сертификата)
- [Настройка платежных систем](#-настройка-платежных-систем)
- [Управление ботом](#-управление-ботом)
- [Мониторинг и логи](#-мониторинг-и-логи)
- [Обновление бота](#-обновление-бота)
- [Устранение неполадок](#-устранение-неполадок)

---

## 🎯 Требования

- VPS с Ubuntu 20.04+ или Debian 11+
- Доменное имя: `yourdomain.com`
- Права root или sudo
- Минимум 1GB RAM, 10GB диска

---

## 🏗️ Архитектура

```
┌─────────────────┐
│   Интернет        │
└────────┬─────────┘
         │ HTTPS:443
         ▼
┌─────────────────┐
│     Nginx       │ ← SSL сертификаты (Let's Encrypt)
│  (порт 443)     │ ← Проксирование на бота
└────────┬────────┘
         │ HTTP:8443
         ▼
┌─────────────────┐
│  Python Bot     │ ← Запущен через systemd
│  (порт 8443)    │ ← Webhook для платежных систем
│                 │ ← Polling для Telegram
└─────────────────┘
```

**Как это работает:**
- Nginx принимает HTTPS запросы на порту 443
- Nginx проксирует запросы на бота (HTTP на порту 8443)
- Бот работает в **webhook режиме** для Telegram (рекомендуется для production)
- Бот обрабатывает webhook от платежных систем через HTTP сервер на порту 8443
- Все webhook запросы идут через Nginx с SSL сертификатом

---

## 🔧 Подготовка сервера

### 1. Обновление системы

```bash
sudo apt update && sudo apt upgrade -y
```

### 2. Установка необходимых пакетов

```bash
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    nginx \
    certbot \
    python3-certbot-nginx \
    git \
    postgresql \
    postgresql-contrib \
    build-essential
```

### 3. Создание пользователя для бота

```bash
sudo useradd -m -s /bin/bash tgmailbot
sudo mkdir -p /home/tgmailbot/tgmailbot
sudo chown tgmailbot:tgmailbot /home/tgmailbot/tgmailbot
```

---

## 📦 Развертывание кода

### 1. Переключение на пользователя бота

```bash
sudo su - tgmailbot
cd /home/tgmailbot
```

### 2. Клонирование репозитория

```bash
# Если используете Git
git clone <your-repository-url> tgmailbot
cd tgmailbot

# Или загрузите код другим способом
```

### 3. Создание виртуального окружения

**⚠️ ВАЖНО:** Бот должен запускаться через интерпретатор Python из виртуального окружения (venv).

```bash
# Создаем виртуальное окружение
python3 -m venv venv

# Активируем виртуальное окружение
source venv/bin/activate
```

### 4. Установка зависимостей

```bash
# Убедитесь, что venv активирован (должна быть префикс (venv) в командной строке)
pip install --upgrade pip
pip install -r requirements.txt
```

### 5. Создание файла `.env`

```bash
nano .env
```

Добавьте следующие переменные:

```env
# Telegram Bot
BOT_TOKEN=your_bot_token_from_botfather
BOT_NAME=your_bot_username
ADMIN_IDS=123456789,987654321
DEVELOPER_IDS=

# Database
DATABASE_URL=sqlite+aiosqlite:///./bot.db
# Или для PostgreSQL:
# DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/tgmailbot

# Платежные системы
YOOKASSA_SHOP_ID=your_shop_id
YOOKASSA_SECRET_KEY=your_secret_key
HELEKET_API_KEY=your_api_key

# Webhook для Telegram (обязательно для production)
WEBHOOK_URL=https://bot.cryptoshop.pro/webhook/telegram

# Webhook для платежных систем
PAYMENT_WEBHOOK_PORT=8443
PAYMENT_WEBHOOK_USE_HTTPS=False
PAYMENT_WEBHOOK_SSL_CERT_PATH=
PAYMENT_WEBHOOK_SSL_KEY_PATH=

# Настройки
SUPPORT_CHAT=@your_support_username
NOTIFICATIONS_CHAT_ID=
REFERRAL_COMMISSION=10
ORDER_RESERVATION_MINUTES=15
BROADCAST_THROTTLE=25
```

### 6. Создание директорий

```bash
mkdir -p logs
chmod 755 logs
```

### 7. Тестовый запуск

**⚠️ ВАЖНО:** Запускайте бота через интерпретатор Python из venv:

```bash
# Убедитесь, что venv активирован
source venv/bin/activate

# Запуск бота через интерпретатор из venv
venv/bin/python main.py
```

Если всё работает, остановите бота (Ctrl+C) и выйдите из пользователя:

```bash
exit
```

**Примечание:** В systemd сервисе бот будет автоматически запускаться через `/home/tgmailbot/tgmailbot/venv/bin/python`, поэтому убедитесь, что venv создан и зависимости установлены.

---

## ⚙️ Настройка Systemd

### 1. Создание сервисного файла

```bash
sudo nano /etc/systemd/system/tgmailbot.service
```

Или скопируйте готовый файл из проекта:

```bash
sudo cp /home/tgmailbot/tgmailbot/tgmailbot.service /etc/systemd/system/tgmailbot.service
```

Содержимое файла:

```ini
[Unit]
Description=Telegram Mail Bot
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=tgmailbot
Group=tgmailbot
WorkingDirectory=/home/tgmailbot/tgmailbot
Environment="PATH=/home/tgmailbot/tgmailbot/venv/bin:/usr/local/bin:/usr/bin:/bin"
Environment="PYTHONUNBUFFERED=1"

# Запуск бота через интерпретатор из venv
ExecStart=/home/tgmailbot/tgmailbot/venv/bin/python /home/tgmailbot/tgmailbot/main.py

# Перезапуск при ошибках
Restart=always
RestartSec=10

# Логирование
StandardOutput=append:/var/log/tgmailbot/out.log
StandardError=append:/var/log/tgmailbot/error.log
SyslogIdentifier=tgmailbot

# Ограничения ресурсов (опционально)
LimitNOFILE=65536
MemoryMax=512M

[Install]
WantedBy=multi-user.target
```

**⚠️ ВАЖНО:** Убедитесь, что путь к интерпретатору Python из venv указан правильно: `/home/tgmailbot/tgmailbot/venv/bin/python`

### 2. Создание директории для логов

```bash
sudo mkdir -p /var/log/tgmailbot
sudo chown tgmailbot:tgmailbot /var/log/tgmailbot
sudo chmod 755 /var/log/tgmailbot
```

### 3. Активация и запуск сервиса

```bash
# Перезагрузка systemd
sudo systemctl daemon-reload

# Включение автозапуска
sudo systemctl enable tgmailbot

# Запуск сервиса
sudo systemctl start tgmailbot

# Проверка статуса
sudo systemctl status tgmailbot
```

### 4. Полезные команды

```bash
# Просмотр статуса
sudo systemctl status tgmailbot

# Просмотр логов
sudo journalctl -u tgmailbot -f

# Перезапуск
sudo systemctl restart tgmailbot

# Остановка
sudo systemctl stop tgmailbot

# Просмотр последних 100 строк логов
sudo journalctl -u tgmailbot -n 100
```

---

## 🌐 Настройка Nginx

### 1. Создание конфигурации Nginx

```bash
sudo nano /etc/nginx/sites-available/tgmailbot
```

Или скопируйте готовый файл из проекта:

```bash
sudo cp /home/tgmailbot/tgmailbot/nginx.conf /etc/nginx/sites-available/tgmailbot
```

Конфигурация для домена **bot.cryptoshop.pro**:

```nginx
# Редирект HTTP на HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name bot.cryptoshop.pro;

    # Для Let's Encrypt
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    # Редирект на HTTPS
    location / {
        return 301 https://$server_name$request_uri;
    }
}

# HTTPS сервер
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name bot.cryptoshop.pro;

    # SSL сертификаты (будут установлены certbot)
    ssl_certificate /etc/letsencrypt/live/bot.cryptoshop.pro/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/bot.cryptoshop.pro/privkey.pem;
    
    # SSL настройки безопасности
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Безопасность заголовков
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Проксирование Telegram webhook
    location /webhook/telegram {
        proxy_pass http://127.0.0.1:8443;
        proxy_http_version 1.1;
        
        # Заголовки для корректной работы
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        
        # Таймауты
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        
        # Буферизация
        proxy_buffering off;
    }

    # Проксирование webhook для платежных систем
    location /webhook/yookassa {
        proxy_pass http://127.0.0.1:8443;
        proxy_http_version 1.1;
        
        # Заголовки для корректной работы
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        
        # Таймауты
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        
        # Буферизация
        proxy_buffering off;
    }

    # Проксирование webhook для Heleket
    location /webhook/heleket {
        proxy_pass http://127.0.0.1:8443;
        proxy_http_version 1.1;
        
        # Заголовки для корректной работы
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        
        # Таймауты
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        
        # Буферизация
        proxy_buffering off;
    }

    # Health check endpoint
    location /health {
        proxy_pass http://127.0.0.1:8443;
        proxy_set_header Host $host;
        access_log off;
    }

    # Запрет доступа к другим путям
    location / {
        return 404;
    }
}
```

### 2. Активация конфигурации

```bash
# Создание символической ссылки
sudo ln -s /etc/nginx/sites-available/tgmailbot /etc/nginx/sites-enabled/

# Удаление дефолтной конфигурации (опционально)
sudo rm /etc/nginx/sites-enabled/default

# Проверка конфигурации
sudo nginx -t

# Если проверка прошла успешно, перезагрузите nginx
sudo systemctl reload nginx
```

### 3. Проверка работы Nginx

```bash
# Статус
sudo systemctl status nginx

# Логи
sudo tail -f /var/log/nginx/error.log
```

---

## 🔒 Установка SSL сертификата

### 1. Получение сертификата Let's Encrypt

```bash
# Убедитесь, что домен указывает на ваш сервер
# Проверьте DNS записи:
# A запись: bot.cryptoshop.pro -> ваш_IP

# Получение сертификата
sudo certbot --nginx -d bot.cryptoshop.pro

# Следуйте инструкциям:
# - Введите email для уведомлений
# - Согласитесь с условиями
# - Выберите редирект HTTP на HTTPS (2)
```

### 2. Автоматическое обновление сертификата

Certbot автоматически создаст cron задачу для обновления сертификата. Проверьте:

```bash
# Тестовое обновление
sudo certbot renew --dry-run

# Просмотр задач обновления
sudo systemctl list-timers | grep certbot
```

### 3. Проверка SSL

```bash
# Проверка сертификата
openssl s_client -connect bot.cryptoshop.pro:443 -servername bot.cryptoshop.pro

# Онлайн проверка: https://www.ssllabs.com/ssltest/
```

---

## 💳 Настройка платежных систем

### Настройка webhook в ЮКасса

1. Войдите в [личный кабинет ЮКасса](https://yookassa.ru/)
2. Перейдите в **Настройки** → **Магазины** → выберите ваш магазин
3. Перейдите в раздел **Webhook**
4. Добавьте URL: `https://bot.cryptoshop.pro/webhook/yookassa`
5. Выберите события:
   - ✅ `payment.succeeded` - успешная оплата
   - ✅ `payment.canceled` - отмена оплаты
6. Сохраните настройки

### Настройка webhook в Heleket

1. Войдите в [личный кабинет Heleket](https://heleket.com/)
2. Перейдите в **Проекты** → выберите ваш проект
3. Перейдите в раздел **Webhook**
4. Добавьте URL: `https://bot.cryptoshop.pro/webhook/heleket`
5. Выберите события:
   - ✅ `payment.success` - успешная оплата
   - ✅ `payment.failed` - неудачная оплата
6. Сохраните настройки

### Настройка webhook для Telegram (обязательно для production)

**⚠️ ВАЖНО:** Для работы в production необходимо настроить webhook режим для Telegram.

1. В файле `.env` добавьте:

```env
# Webhook для Telegram (обязательно для production)
WEBHOOK_URL=https://bot.cryptoshop.pro/webhook/telegram

# Webhook сервер для платежных систем
PAYMENT_WEBHOOK_PORT=8443
PAYMENT_WEBHOOK_USE_HTTPS=False
```

2. После настройки SSL сертификата и запуска бота, webhook будет автоматически установлен.

3. Проверка работы webhook:

```bash
# Проверка health check
curl https://bot.cryptoshop.pro/health

# Должен вернуть: OK

# Проверка статуса webhook через API Telegram (опционально)
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

---

## 🎮 Управление ботом

### Основные команды

```bash
# Статус
sudo systemctl status tgmailbot

# Запуск
sudo systemctl start tgmailbot

# Остановка
sudo systemctl stop tgmailbot

# Перезапуск
sudo systemctl restart tgmailbot

# Просмотр логов в реальном времени
sudo journalctl -u tgmailbot -f

# Просмотр последних 100 строк
sudo journalctl -u tgmailbot -n 100

# Просмотр логов с определенного времени
sudo journalctl -u tgmailbot --since "2024-01-01 00:00:00"
```

### Просмотр логов приложения

```bash
# Логи из файлов
tail -f /var/log/tgmailbot/out.log
tail -f /var/log/tgmailbot/error.log

# Логи бота
tail -f /home/tgmailbot/tgmailbot/logs/bot.log
```

---

## 📊 Мониторинг и логи

### Мониторинг ресурсов

```bash
# Использование памяти и CPU
top -p $(pgrep -f "python.*main.py")

# Или используйте htop
sudo apt install htop
htop
```

### Проверка работы webhook сервера

```bash
# Проверка порта
sudo netstat -tlnp | grep 8443

# Или
sudo ss -tlnp | grep 8443

# Должно быть: LISTEN на 0.0.0.0:8443
```

### Мониторинг Nginx

```bash
# Статус
sudo systemctl status nginx

# Логи доступа
sudo tail -f /var/log/nginx/access.log

# Логи ошибок
sudo tail -f /var/log/nginx/error.log
```

---

## 🔄 Обновление бота

### Процесс обновления

```bash
# 1. Остановка бота
sudo systemctl stop tgmailbot

# 2. Переключение на пользователя бота
sudo su - tgmailbot
cd /home/tgmailbot/tgmailbot

# 3. Активация виртуального окружения
source venv/bin/activate

# 4. Обновление кода
git pull
# Или загрузите новый код другим способом

# 5. Активация виртуального окружения и обновление зависимостей (если изменились)
source venv/bin/activate
pip install -r requirements.txt

# 6. Выход из пользователя
exit

# 7. Запуск бота
sudo systemctl start tgmailbot

# 8. Проверка статуса
sudo systemctl status tgmailbot
```

### Автоматическое обновление (опционально)

Можно создать скрипт для автоматического обновления:

```bash
sudo nano /usr/local/bin/update-tgmailbot.sh
```

```bash
#!/bin/bash
systemctl stop tgmailbot
sudo -u tgmailbot bash -c "cd /home/tgmailbot/tgmailbot && source venv/bin/activate && git pull && pip install -r requirements.txt"
systemctl start tgmailbot
systemctl status tgmailbot
```

**⚠️ ВАЖНО:** При обновлении убедитесь, что виртуальное окружение (venv) создано и зависимости установлены, так как systemd запускает бота через `/home/tgmailbot/tgmailbot/venv/bin/python`.

```bash
sudo chmod +x /usr/local/bin/update-tgmailbot.sh
```

---

## 🐛 Устранение неполадок

### Бот не запускается

```bash
# 1. Проверьте статус
sudo systemctl status tgmailbot

# 2. Проверьте логи
sudo journalctl -u tgmailbot -n 50

# 3. Проверьте .env файл
sudo -u tgmailbot cat /home/tgmailbot/tgmailbot/.env

# 4. Проверьте права доступа
ls -la /home/tgmailbot/tgmailbot/

# 5. Попробуйте запустить вручную через интерпретатор из venv
sudo -u tgmailbot bash -c "cd /home/tgmailbot/tgmailbot && /home/tgmailbot/tgmailbot/venv/bin/python main.py"
```

### Webhook не работает

```bash
# 1. Проверьте, что бот запущен
sudo systemctl status tgmailbot

# 2. Проверьте, что порт 8443 открыт
sudo netstat -tlnp | grep 8443

# 3. Проверьте Nginx
sudo nginx -t
sudo systemctl status nginx

# 4. Проверьте логи Nginx
sudo tail -f /var/log/nginx/error.log

# 5. Проверьте health check
curl https://bot.cryptoshop.pro/health

# 6. Проверьте SSL сертификат
sudo certbot certificates
```

### Проблемы с базой данных

```bash
# Для SQLite - проверьте права
sudo chown tgmailbot:tgmailbot /home/tgmailbot/tgmailbot/bot.db
sudo chmod 644 /home/tgmailbot/tgmailbot/bot.db

# Для PostgreSQL - проверьте подключение
sudo -u postgres psql -c "\l"
sudo -u postgres psql -d tgmailbot_db -c "SELECT 1;"
```

### Проблемы с SSL

```bash
# Проверка сертификата
sudo certbot certificates

# Обновление сертификата вручную
sudo certbot renew

# Проверка конфигурации Nginx
sudo nginx -t
```

### Очистка логов

```bash
# Очистка логов systemd
sudo journalctl --vacuum-time=7d

# Очистка логов приложения
sudo truncate -s 0 /var/log/tgmailbot/out.log
sudo truncate -s 0 /var/log/tgmailbot/error.log
```

---

## 🔐 Безопасность

### Рекомендации по безопасности

1. **Firewall (UFW)**
   ```bash
   sudo ufw allow 22/tcp
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw enable
   ```

2. **Регулярные обновления**
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

3. **Резервное копирование**
   ```bash
   # Создайте скрипт для бэкапа БД
   sudo nano /usr/local/bin/backup-tgmailbot.sh
   ```

4. **Мониторинг**
   - Настройте мониторинг ресурсов сервера
   - Настройте алерты при падении бота

---

## 📝 Чеклист развертывания

- [ ] Сервер подготовлен и обновлен
- [ ] Пользователь `tgmailbot` создан
- [ ] Код загружен на сервер
- [ ] Виртуальное окружение создано
- [ ] Зависимости установлены
- [ ] Файл `.env` настроен
- [ ] Systemd сервис создан и запущен
- [ ] Nginx настроен и запущен
- [ ] SSL сертификат установлен
- [ ] Webhook URL настроены в платежных системах
- [ ] Бот работает и отвечает на команды
- [ ] Webhook тестированы
- [ ] Логи проверены
- [ ] Firewall настроен
- [ ] Резервное копирование настроено

---

## 📞 Поддержка

Если возникли проблемы:

1. Проверьте логи: `sudo journalctl -u tgmailbot -f`
2. Проверьте статус сервисов: `sudo systemctl status tgmailbot nginx`
3. Проверьте конфигурацию: `sudo nginx -t`
4. Проверьте порты: `sudo netstat -tlnp | grep 8443`

---

**Готово!** 🎉 Ваш бот развернут и готов к работе!

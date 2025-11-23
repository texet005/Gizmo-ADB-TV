# Gizmo-ADB-TV

GUI‑утилита для автоматического управления Smart TV по ADB в связке с
биллингом **Gizmo**.

## Основные возможности

### TVGIZMOADB

-   Мониторинг активных сессий Gizmo Host ID
-   Автоматическое выключение ТВ через ADB (`keyevent 26`)
-   Профили настроек, тёмная/светлая тема
-   Вкладка диагностики (API, ADB, запуск доп. GUI)
-   Логи в `tvgizmo.log`

### TV PSV2

-   Панель управления для нескольких ТВ
-   Таймеры (countdown, count‑up), расчёт стоимости
-   Подключение ADB, статус ONLINE/OFFLINE
-   Ручное включение/выключение

## Установка

Через инструменты разработчика разблокируйте "Отладка по USB" "Отладка по сети"
А так-же чтобы постоянно не бегать, установите статический IP. 
После проверьте пингуется ли через админский пк телевизор.
Если всё нормально, продолжайте далее.


``` bash
git clone https://github.com/texet005/Gizmo-ADB-TV.git
cd Gizmo-ADB-TV
pip install -r requirements.txt
```

## Настройка config.env

``` env
API_BASE=https://your-gizmo-server/api
GIZMO_ADMIN_USERNAME=ADMIN
GIZMO_ADMIN_PASSWORD=ADMIN
GIZMO_HOST_ID=7
ADB_PATH=./adb/adb.exe
TV_ADB_TARGET=192.168.1.100:5555
POLL_INTERVAL_SEC=5
```

## Использование

### Мониторинг Gizmo и автоматическая работа скрипта

``` bash
python tvgizmoadb.py
```

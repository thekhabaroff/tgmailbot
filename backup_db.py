"""Скрипт для резервного копирования базы данных"""
import shutil
from datetime import datetime
import os
import sys

def backup_sqlite():
    """Создание резервной копии SQLite БД"""
    db_file = "bot.db"
    if not os.path.exists(db_file):
        print("❌ База данных не найдена!")
        return False
    
    # Создаем папку для бэкапов
    backup_dir = "backups"
    os.makedirs(backup_dir, exist_ok=True)
    
    # Имя файла бэкапа
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(backup_dir, f"bot_backup_{timestamp}.db")
    
    try:
        # Копируем файл
        shutil.copy2(db_file, backup_file)
        file_size = os.path.getsize(backup_file) / 1024  # Размер в KB
        print(f"✅ Резервная копия создана: {backup_file}")
        print(f"   Размер: {file_size:.2f} KB")
        
        # Удаляем старые бэкапы (оставляем последние 10)
        backups = sorted(
            [f for f in os.listdir(backup_dir) if f.startswith("bot_backup_") and f.endswith(".db")],
            key=lambda x: os.path.getmtime(os.path.join(backup_dir, x))
        )
        
        if len(backups) > 10:
            removed_count = 0
            for old_backup in backups[:-10]:
                old_backup_path = os.path.join(backup_dir, old_backup)
                os.remove(old_backup_path)
                removed_count += 1
            if removed_count > 0:
                print(f"🗑️ Удалено старых бэкапов: {removed_count}")
        
        return True
    except Exception as e:
        print(f"❌ Ошибка при создании резервной копии: {e}")
        return False


def list_backups():
    """Показать список резервных копий"""
    backup_dir = "backups"
    if not os.path.exists(backup_dir):
        print("📁 Папка с резервными копиями не найдена")
        return
    
    backups = sorted(
        [f for f in os.listdir(backup_dir) if f.startswith("bot_backup_") and f.endswith(".db")],
        key=lambda x: os.path.getmtime(os.path.join(backup_dir, x)),
        reverse=True
    )
    
    if not backups:
        print("📭 Резервных копий не найдено")
        return
    
    print(f"📦 Найдено резервных копий: {len(backups)}\n")
    for i, backup in enumerate(backups, 1):
        backup_path = os.path.join(backup_dir, backup)
        file_size = os.path.getsize(backup_path) / 1024
        mod_time = datetime.fromtimestamp(os.path.getmtime(backup_path))
        print(f"{i}. {backup}")
        print(f"   Размер: {file_size:.2f} KB")
        print(f"   Дата: {mod_time.strftime('%Y-%m-%d %H:%M:%S')}\n")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        list_backups()
    else:
        print("🔄 Создание резервной копии базы данных...\n")
        backup_sqlite()


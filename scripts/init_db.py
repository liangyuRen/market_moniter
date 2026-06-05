"""初始化数据库 — 创建表结构"""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from src.storage.database import init_db

if __name__ == "__main__":
    init_db()
    print("数据库初始化完成.")

"""
pytest 全域設定:把 /home/user 加入 sys.path,
讓 AutoTrading 可作為頂層套件被 import。
"""
import sys
from pathlib import Path

# /home/user/AutoTrading/../ = /home/user
sys.path.insert(0, str(Path(__file__).parent.parent))

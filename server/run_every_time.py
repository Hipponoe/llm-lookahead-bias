import time
import subprocess
from datetime import datetime

def run_program():
    """每分钟执行一次目标 Python 程序"""
    while True:
        try:
            # 获取当前时间
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[{now}] 开始执行目标程序...")

            # ===================== 重要配置 =====================
            # 这里替换成你要每分钟运行的 Python 文件路径
            TARGET_SCRIPT = "news_collector.py"
            TARGET_ANALYZER = "news_analyzer.py"  
            # ====================================================

            # 运行目标脚本（会等待它执行完）
            # stdout和stderr会输出到控制台
            subprocess.run(["python", TARGET_SCRIPT], check=True)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{now}] 新闻收集程序执行完成 ✅")
            subprocess.run(["python", TARGET_ANALYZER], check=True)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{now}] 新闻分析程序执行完成 ✅")

        except subprocess.CalledProcessError:
            print(f"[{now}] 目标程序执行出错 ❌")
        except Exception as e:
            print(f"[{now}] 调度异常：{str(e)}")

        # 等待 60 秒 = 1 分钟
        time.sleep(60)

if __name__ == "__main__":
    print("=== 每分钟自动运行脚本已启动 ===")
    print("按 Ctrl + C 停止\n")
    run_program()
# daily_checker.py
import datetime
import subprocess
import sys

def should_run_today():
    """判断今天是否需要运行（周一到周五返回True）"""
    today = datetime.datetime.now().weekday()
    return today < 5  # 0=周一, 1=周二, 2=周三, 3=周四, 4=周五

def run_checker():
    """执行准确性检查程序"""
    try:
        print(f"[{datetime.datetime.now()}] 开始执行 accuracy_checker_v3.py")
        result = subprocess.run(
            ['python', 'accuracy_checker_v3.py'],
            # capture_output=True,
            # text=True
        )
        
        if result.returncode == 0:
            print(f"✅ 执行成功\n输出: {result.stdout}")
        else:
            print(f"❌ 执行失败\n错误: {result.stderr}")
            
    except FileNotFoundError:
        print("错误: 找不到 accuracy_checker_v3.py，请确保文件在当前目录")
    except Exception as e:
        print(f"执行出错: {str(e)}")

def main():
    if should_run_today():
        print("今天是工作日，开始执行检查程序...")
        run_checker()
    else:
        print("今天是周末，跳过执行")

if __name__ == "__main__":
    main()
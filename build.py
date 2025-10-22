import os
import subprocess
import sys

def build_exe():
    """使用PyInstaller打包GUI应用"""
    
    # PyInstaller命令参数
    cmd = [
        "pyinstaller",
        "--onefile",                    # 打包成单个exe文件
        "--windowed",                   # 不显示控制台窗口
        "--icon=Arcueid.ico",          # 设置图标
        "--name=ICP_Query_GUI",        # 设置exe文件名
        "--add-data=model_data;model_data",  # 添加模型文件
        "--add-data=Arcueid.ico;.",    # 添加图标文件
        "--hidden-import=PyQt5.QtCore",
        "--hidden-import=PyQt5.QtGui", 
        "--hidden-import=PyQt5.QtWidgets",
        "--hidden-import=aiohttp",
        "--hidden-import=cv2",
        "--hidden-import=numpy",
        "--hidden-import=onnxruntime",
        "--hidden-import=PIL",
        "--hidden-import=yaml",
        "--hidden-import=crypto",
        "--hidden-import=ujson",
        "--hidden-import=cachetools",
        "--hidden-import=openpyxl",
        "gui_main.py"                  # 主程序文件
    ]
    
    print("开始打包...")
    print("命令:", " ".join(cmd))
    
    try:
        # 执行打包命令
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("打包成功!")
        print("输出:", result.stdout)
        
        # 检查生成的文件
        exe_path = "dist/ICP_Query_GUI.exe"
        if os.path.exists(exe_path):
            size = os.path.getsize(exe_path) / (1024 * 1024)  # MB
            print(f"生成的exe文件: {exe_path}")
            print(f"文件大小: {size:.2f} MB")
        else:
            print("警告: 未找到生成的exe文件")
            
    except subprocess.CalledProcessError as e:
        print("打包失败!")
        print("错误:", e.stderr)
        return False
    except Exception as e:
        print(f"打包过程中出现错误: {e}")
        return False
    
    return True

if __name__ == "__main__":
    build_exe()

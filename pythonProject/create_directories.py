import os


def create_project_structure():
    """创建项目文件夹结构"""
    directories = [
        'data/raw',
        'data/processed',
        'data/intermediate',
        'src',
        'outputs/figures',
        'outputs/results'
    ]

    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        print(f"创建目录: {directory}")

    print("项目文件夹结构创建完成！")


if __name__ == "__main__":
    create_project_structure()
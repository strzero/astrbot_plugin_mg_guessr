import os
from glob import glob
from tinydb import TinyDB
from screenshot import capture_screenshots
from tqdm import tqdm  # 导入tqdm库
from selenium.common.exceptions import TimeoutException  # 导入TimeoutException
from concurrent.futures import ThreadPoolExecutor, as_completed

# 载入数据库
db_path = '/opt/wiki-check-bot-docker/data/songs_db.json'
db = TinyDB(db_path)

# 获取arc_data表的数据
arc_data = db.table('arc_data').all()

# 图像保存路径
image_path = '/opt/wiki-check-bot-docker/data/image'

# 定义处理每首歌的函数
def process_song(item):
    song_title = item.get('曲名', '')
    if song_title:  # 如果“曲名”存在
        # 构建可能的文件路径，查找类似 {song_title}-a* 的文件
        file_pattern = os.path.join(image_path, f"{song_title}-a*")
        existing_files = glob(file_pattern)

        # 如果文件已经存在，跳过该曲目
        if existing_files:
            return f"Skipping {song_title}, file already exists."

        try:
            # 执行截图操作
            capture_screenshots(song_title)
            return f"Processed {song_title} successfully."
        except TimeoutException:
            return f"TimeoutException occurred for {song_title}, skipping this song."
        except Exception as e:
            return f"Error occurred for {song_title}: {e}"

# 使用ThreadPoolExecutor进行并行处理
with ThreadPoolExecutor(max_workers=10) as executor:
    # 使用tqdm来显示进度条，total参数设置为arc_data的长度
    futures = [executor.submit(process_song, item) for item in arc_data]
    
    # 遍历返回的future对象并显示结果
    for future in tqdm(as_completed(futures), total=len(futures), desc="Processing songs", unit="song"):
        result = future.result()
        tqdm.write(result)

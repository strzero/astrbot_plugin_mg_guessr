from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import os

def capture_screenshots(title: str):
    """
    截取指定网页的截图，按照指定规则保存。

    :param title: 用于过滤和命名的标题
    """
    # 固定的配置
    url = f'https://arcwiki.mcd.blue/{title}'
    driver_path = '/AstrBot/data/chrome/chromedriver-linux64/chromedriver'
    chrome_binary_path = '/AstrBot/data/chrome/chrome-linux64/chrome'
    save_dir = '/AstrBot/data/image'

    # 创建存储截图的目录（如果不存在的话）
    os.makedirs(save_dir, exist_ok=True)

    # 配置 Chrome 选项
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.binary_location = chrome_binary_path
    service = Service(driver_path)

    # 启动浏览器
    driver = webdriver.Chrome(service=service, options=chrome_options)

    # 设置浏览器窗口的宽度为450px，高度为900px
    driver.set_window_size(450, 900)

    driver.get(url)

    # 使用显式等待确保页面完全加载
    try:
        # 等待 .mw-parser-output 元素加载完毕（最大等待时间 10 秒）
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '.mw-parser-output'))
        )

        # 获取所有 .mw-parser-output li 元素，排除掉 div 中的 li 和嵌套在其他 li 中的 li
        list_elements = driver.find_elements(By.CSS_SELECTOR, '.mw-parser-output > ul > li:not(.mw-parser-output div li)')
        for i, element in enumerate(list_elements, start=1):
            # 获取每个元素的文本
            text = element.text
            if title in text:
                continue  # 如果文本包含 title，则跳过

            # 截图并保存到指定路径
            screenshot_name = os.path.join(save_dir, f'{title}-a-{i}.png')
            element.screenshot(screenshot_name)

        # 获取所有不嵌套的 .comment-thread 元素
        comment_elements = driver.find_elements(By.CSS_SELECTOR, '.comment-thread:not(.comment-thread .comment-thread)')
        for i, element in enumerate(comment_elements, start=1):
            # 获取每个元素的文本
            text = element.text
            if title in text:
                continue  # 如果文本包含 title，则跳过

            # 截图并保存到指定路径
            screenshot_name = os.path.join(save_dir, f'{title}-b-{i}.png')
            element.screenshot(screenshot_name)

    finally:
        # 关闭浏览器
        driver.quit()


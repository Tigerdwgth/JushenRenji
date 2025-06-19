from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pickle
import os
# os.environ['DISPLAY']= ':0'  # 设置 DISPLAY 环境变量
import pyautogui as pag

pag.FAILSAFE = False

from selenium.webdriver.chrome.options import Options

PREFIX="【CVPR2025】"

def prefix_preprocess(PREFIX):
    if not PREFIX:return ""
    if not PREFIX.endswith("】"):
        PREFIX = PREFIX + "】"
    if not PREFIX.startswith("【"):
        PREFIX = "【" + PREFIX
    return PREFIX
def upload_video_to_bilibili(video_path, video_title, video_tags, video_description, PREFIX=""):
    PREFIX = prefix_preprocess(PREFIX)
    # Cookies 文件路径
    cookies_file = "bilibili_cookies.pkl"

    # 初始化浏览器
    options = Options()
    options.add_argument("--start-maximized")

    # 设置允许通知
    prefs = {
        "profile.default_content_setting_values.notifications": 1  # 1 表示允许，2 表示阻止
    }
    options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        # 检查是否存在已保存的 Cookies
        if os.path.exists(cookies_file):
            # 打开登录页面
            driver.get("https://www.bilibili.com/")
            time.sleep(5)

            # 加载 Cookies
            with open(cookies_file, "rb") as file:
                cookies = pickle.load(file)
                for cookie in cookies:
                    # cookie['domain']='www.bilibili.com'
                    driver.add_cookie(cookie)
                    print(cookie)

            # 刷新页面以应用 Cookies
            driver.get("https://www.bilibili.com/")
            driver.refresh()
            time.sleep(5)
        else:
            # 打开登录页面
            driver.get("https://passport.bilibili.com/login")
            time.sleep(30)  # 手动登录

            # 保存 Cookies
            with open(cookies_file, "wb") as file:
                pickle.dump(driver.get_cookies(), file)

        # 打开上传页面
        driver.get("https://member.bilibili.com/platform/upload/video/frame?spm_id_from=333.1387.top_bar.upload")
        time.sleep(5)

        # #点击投稿按钮
        # submit_button = driver.find_element(By.XPATH, '//button[contains(text(), "投稿")]')
        # submit_button.click()
        # 上传视频文件
        upload_input = driver.find_element(By.XPATH, '//input[@accept=".mp4,.flv,.avi,.wmv,.mov,.webm,.mpeg4,.ts,.mpg,.rm,.rmvb,.mkv,.m4v" and @type="file"]')
        upload_input.send_keys(video_path)
        time.sleep(15)  # 等待视频上传完成
        cover_path = video_path.replace(".mp4", ".png")
        
        #绝对路径
        cover_path = os.path.abspath(cover_path)
        # print(f"视频上传成功，封面路径: {cover_path}")
        #with disk path
        # cover_path = os.path.join(os.getcwd(), cover_path)
        print(f"视频上传成功，封面路径: {cover_path}")
        # 查找所有输入框
        inputs = driver.find_elements(By.TAG_NAME, "input")
        for i, input_element in enumerate(inputs):
            print(f"输入框 {i + 1}: {input_element.get_attribute('outerHTML')}")

        # 查找所有文本区域
        textareas = driver.find_elements(By.TAG_NAME, "textarea")
        for i, textarea in enumerate(textareas):
            print(f"文本区域 {i + 1}: {textarea.get_attribute('outerHTML')}")
        #查找所有按钮
        elements = driver.find_elements(By.XPATH, 'button')
        for i, element in enumerate(elements):
            print(f"元素 {i + 1}: {element.get_attribute('outerHTML')}")
        #查找所有简介
        elements = driver.find_elements(By.XPATH, '简介')+driver.find_elements(By.XPATH, '了解')
        for i, element in enumerate(elements):
            print(f"元素 {i + 1}: {element.get_attribute('outerHTML')}")
        #raise Exception("停止")
        # 填写标题
        title_input = driver.find_element(By.XPATH, '//input[@type="text" and @maxlength="80"]')
        title_input.clear()
        title_input.send_keys(PREFIX+video_title)


        # 填写标签

        tags_input = driver.find_element(By.XPATH, '//input[@type="text" and @maxlength="20"]')
        for tag in video_tags.split(","):
            time.sleep(2)  # 等待标签输入框加载
            tags_input.send_keys(tag)
            tags_input.send_keys(Keys.ENTER)



        # # # 填写简介
        # //*[@id="video-up-app"]/div[2]/div[1]/div[2]/div[7]/div/div[2]/div/div[1]/div[1]
        #/html/body/div[1]/div[3]/div[4]/div[2]/div/div/div/micro-app/micro-app-body/div[1]/div[2]/div[1]/div[2]/div[7]/div/div[2]/div/div[1]/div[1]
        #<div class="ql-editor ql-blank" data-gramm="false" contenteditable="true" data-placeholder="填写更全面的相关信息，让更多的人能找到你的视频吧"><p><br></p></div>
        description_input = driver.find_element(By.XPATH, '//div[@class="ql-editor ql-blank" and @contenteditable="true"]')
        description_input.send_keys(video_description)
        #向上滚动界面
        driver.execute_script("window.scrollTo(0, 0);")
        
        #上传封面
        # 上传封面
        # # 创建视频同名的jpg文件路径

        # 检查封面文件是否存在
        if os.path.exists(cover_path):
            try:
                # 点击更改封面按钮
                print("点击更改封面按钮")
                # 定位更改封面按钮
                xpath_change_cover = '//div[@class="cover-upload-mask-btn"]/span[contains(text(), "更改封面")]'
                change_cover_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, xpath_change_cover))
                )
                change_cover_button.click()
                time.sleep(2)
                print("点击更改封面按钮成功")

                upload_cover_tab = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, '//div[contains(@class, "cover-select-header-tab-item")]/div[text()="上传封面"]'))
                )
                upload_cover_tab.click()
                time.sleep(2)
                
                #点击上传图片按钮
                # <button class="bcc-button bcc-button--primary large" data-reporter-id="72" style="width: 100px; height: 32px; margin-top: 6px;"><!----><span> 上传图片 </span></button>
                upload_cover_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, '//button[contains(@class, "bcc-button--primary") and span[text()=" 上传图片 "]]'))
                )
                upload_cover_button.click()
                time.sleep(3)
                
                # upload_cover_input = WebDriver((By.XPATH, '//input[@type="file" and @accept=".jpg,.jpeg,.png"]'))
                # )
                # <input accept="image/png, image/jpeg" type="file" style="display: none;">
                # upload_cover_input=driver.find_element(By.XPATH, '//input[@accept="image/png, image/jpeg" and @type="file"]')
                #输入cover_path 然后回车
                print("输入封面路径")
                # for i in range(10):
                    # pag.press('tab')
                # pag.write(cover_path,interval=0.1)
                import pyperclip
                pyperclip.copy(cover_path)
                
                pag.hotkey('ctrl', 'v')
                pag.press('enter')
                # upload_cover_input.send_keys(cover_path)
                time.sleep(5)  # 等待封面上传完成
                pag.press('enter')
                time.sleep(2) 
                # input()

                # print("封面上传成功")
                #press 完成
                complete_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, '//span[contains(text(), "完成")]'))
                )
                complete_button.click()
            except Exception as e:
                print(f"封面上传失败: {e}")
        else:
            print(f"封面图片不存在: {cover_path}")
        
        input()
        # 提交投稿
        submit_button = driver.find_element(By.XPATH, '//span[@class="submit-add" and text()="立即投稿"]')
        submit_button.click()
        time.sleep(15)
        print("视频上传成功！")
    except Exception as e:
        print(f"发生错误: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    # 视频文件路径和信息
    video_path  = r"F:\PaperReadingAgent\output\daily_summary.mp4"
    import datetime
    video_title = "封面上传功能测试"+datetime.datetime.now().strftime('%Y-%m-%d')
    video_tags = "人工智能,具身智能,机器人,模仿学习,强化学习,自动驾驶,具身人机"
    video_description = video_title
    upload_video_to_bilibili(video_path, video_title, video_tags, video_description)

    pass

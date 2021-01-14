from flask import Flask, request, abort
import os,sys
from linebot import (
    LineBotApi, WebhookHandler
)
from linebot.exceptions import (
    InvalidSignatureError
)
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
)

import requests
from bs4 import BeautifulSoup
import re
import pickle
import time
import redis
import json
from datetime import datetime, timedelta

app = Flask(__name__)

# get channel_secret and channel_access_token from your environment variable
channel_secret = os.getenv('LINE_CHANNEL_SECRET', None)
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', None)

redis_host = os.getenv('REDIS_HOME', None)
redis_port = os.getenv('REDIS_PORT', None)
redis_password = os.getenv('REDIS_PASSWD', None)

cache_time = os.getenv('CACHE_TIME', 5*60)

if channel_secret is None or channel_access_token is None:
    print('Specify LINE_CHANNEL_SECRET and LINE_CHANNEL_ACCESS_TOKEN as environment variables.')
    sys.exit(1)
if redis_host is None or redis_port is None:
    print('Specify REDIS_HOME and REDIS_PORT as environment variables.')
    sys.exit(1)

pool = redis.ConnectionPool(host=redis_host, port=redis_port, decode_responses=True, password=redis_password)
redis_client = redis.Redis(connection_pool=pool)

try:
    redis_client.ping()
    # redis_client.pfadd(datetime.today().strftime("%Y/%m/%d"),"A")
    # redis_client.pfadd((datetime.today()+timedelta(days=1)).strftime("%Y/%m/%d"),"B")
    # redis_client.pfadd((datetime.today()+timedelta(days=2)).strftime("%Y/%m/%d"),"C")
    # redis_client.pfadd((datetime.today()+timedelta(days=3)).strftime("%Y/%m/%d"),"A")
    # print("----------------------------------------------")
    # print(redis_client.pfcount(datetime.today().strftime("%Y/%m/%d")))
except Exception as e:
    print('---------[Error]---------')
    print(e)
    print('redis connect error')
    print('host:'+redis_host)
    print('port:'+redis_port)
    print('pwd:' + redis_password)
    sys.exit(1)
print('connected to redis "{}"'.format(redis_host)) 

line_bot_api = LineBotApi(channel_access_token)
handler = WebhookHandler(channel_secret)

def get_doctors_url(refresh = False):
    global redis_client
    # if os.path.isfile("links.pickle") and (refresh == False):
    #     with open('links.pickle', 'rb') as handle:
    #         all_link = pickle.load(handle)
    #     if (datetime.fromtimestamp(time.time()) - datetime.fromtimestamp(all_link['time'])).seconds > 5 * 60:
    #         print("refresh links data")
    #         return get_doctors_url(True)
    #     else:
    #         print("history links data")
    #         return all_link
    rlinks = redis_client.get('links')
    if rlinks != None and refresh == False:
        print("history links data")
        return json.loads(rlinks)
    else:
        print("refresh links data")
        r = requests.get("http://www.ktgh.com.tw/Reg_Clinic_Progress.asp?CatID=39&ModuleType=Y")
        rt = r.text
        rs = BeautifulSoup(rt, 'html.parser')
        sizebox = rs.find(id='Sizebox')
        links = sizebox.find_all(attrs={"onclick": re.compile("^javascript:location.href")})
        all_link = {}
        for link in links:
            _link = (link['onclick'].split('\'')[1])
            _title = (link.find('a')['title'])
            all_link[_title] = _link
        # all_link['time'] = time.time()
        # with open('links.pickle', 'wb') as handle:
        #     pickle.dump(all_link, handle, protocol=pickle.HIGHEST_PROTOCOL)
        redis_client.setex("links", cache_time,json.dumps(all_link))
        return all_link

def get_doctor_data(c, all_link,refresh = False):
    global redis_client
    # if os.path.isfile(c + ".pickle") and (refresh == False):
    #     with open(c+'.pickle', 'rb') as handle:
    #         pkl = pickle.load(handle)
    #     if (datetime.fromtimestamp(time.time()) - datetime.fromtimestamp(pkl['time'])).seconds > 5 * 60:
    #         print("refresh doctor data")
    #         return get_doctor_data(c, all_link,True)
    #     else:
    #         print("history doctor data")
    #         return pkl['str']
    data = redis_client.get('doctor_' + c)
    if data != None and refresh == False:
        print("history doctor data")
        data = json.loads(data)
        return data['str']
    else:
        print("refresh doctor data")
        r = requests.get("http://www.ktgh.com.tw/" + all_link[c])
        rt = r.text
        rs = BeautifulSoup(rt, 'html.parser')
        _str = str(c) + '\r\n--------------------------------\r\n'
        table = rs.find_all(attrs={'summary': '排版用表格'})[10]
        doctors = table.find_all("a")
        for doctor in doctors:
            _time = doctor.parent.findNext('td')
            if ('已' in str(_time.text)):
                text1 = str(_time.text).split('已')[0] + '\r\n'
                text1 = text1 + '已' + str(_time.text).split('已')[1]
            else:
                text1 = str(_time.text)

            if ('(' in doctor.text):
                continue
        #     print(doctor.text)
        #     print(_time.text)    
            _str += doctor.text + "\r\n" + text1 + "\r\n" + "--------------------------------\r\n"
        _str = _str + '最後更新時間:' + str(datetime.now().strftime("%Y/%m/%d %H:%M"))
        pkl = {
            'str': _str,
            'time': time.time(),
        }
        # with open(c+'.pickle', 'wb') as handle:
        #     pickle.dump(pkl, handle, protocol=pickle.HIGHEST_PROTOCOL)
        redis_client.setex("doctor_" + c, cache_time,json.dumps(pkl))
        return _str

def get_doctor_str(c):
    all_link = get_doctors_url()
    if str(c).isnumeric():
        try:
            c = int(c)
            c = list(all_link)[c-1]
        except Exception as e:
            print(e)
            c = 'error'
    print(c)
    if c not in all_link:
        return "醫生還未開始看診"
    str_ = get_doctor_data(c ,all_link)
    return str_

# 此為 Webhook callback endpoint
@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body（負責）
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'

# decorator 負責判斷 event 為 MessageEvent 實例，event.message 為 TextMessage 實例。所以此為處理 TextMessage 的 handler
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    # 決定要回傳什麼 Component 到 Channel
    global redis_client
    user_id = event.source.user_id
    redis_client.pfadd("usrcnt_" + datetime.today().strftime("%Y/%m/%d"),user_id)
    if (event.message.text == '列表' or event.message.text == '0'):
        all_links = get_doctors_url()
        text = ""
        i = 1
        for a,value in all_links.items():
            if a=='time':
                continue
            text += str(i) + ":" + str(a) + "\r\n"
            i += 1
    elif ('admin' in str(event.message.text)):
        message = str(event.message.text).split(' ')
        pwd = message[1]
        if (pwd == '666'):
            cmd = message[2]
            if (cmd == 'usrcnt'):
                text = "今日使用人數:" + str(redis_client.pfcount("usrcnt_" + datetime.today().strftime("%Y/%m/%d")))
            if (cmd == 'daycnt'):
                text = ""
                for x in redis_client.keys("daycnt_*"):
                    text += str(x) + " = "+ str(redis_client.get(x)) + "\r\n"
                    redis_client.expire(x, 5 * 60)

    else:
        cnt = redis_client.get("daycnt_" + str(datetime.now().strftime("%Y/%m/%d-%H")))
        if (cnt == None):
            redis_client.set("daycnt_" + str(datetime.now().strftime("%Y/%m/%d-%H")), 1)
        else:
            redis_client.incr("daycnt_" + str(datetime.now().strftime("%Y/%m/%d-%H")), 1)
        text = get_doctor_str(event.message.text)
        print(user_id)
        print("text:" + text)

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=text))


if __name__ == "__main__":
    # Only for debugging while developing
    app.run(host='0.0.0.0', debug=False, port=80)
    # print(get_doctors_url())
    # print(get_doctor_str('一般內科', get_doctors_url()))
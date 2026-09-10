from flask import Flask, jsonify, request, render_template, session, redirect, url_for
from urllib.parse import urlparse, urljoin
from functools import wraps
import json
import os
import urllib.request
import re
import uuid
from urllib.parse import quote
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta, timezone

# app.py はプロジェクト直下に置く。
# 実体（templates / static / data）は bousai_app/ 配下にあるので、そこを参照する。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, 'bousai_app')

app = Flask(
    __name__,
    template_folder=os.path.join(APP_DIR, 'templates'),
    static_folder=os.path.join(APP_DIR, 'static'),
)
app.secret_key = 'your-secret-key-here'

# 管理者認証情報
ADMIN_CREDENTIALS = {
    'admin': '123'
}

# ────────────────────────────────
# 気象警報・注意報設定
PREFECTURE_CODE = "020000"  # 青森県
AREA_NAME = "青森市"

# 青森市の市区町村コード
AREA_CODE = "0220100"
AREA_LATITUDE = 40.8221
AREA_LONGITUDE = 140.7474
CURRENT_LOCATION_NAME = "青森駅"
CURRENT_LOCATION_LATITUDE = 40.8296
CURRENT_LOCATION_LONGITUDE = 140.7345

WARNING_URL = (
    f"https://www.jma.go.jp/bosai/warning/data/r8/{PREFECTURE_CODE}.json"
)

JST = timezone(timedelta(hours=9))

# 警報・注意報のコード一覧
WARNING_CODES = {
    "00": "解除",
    "02": "暴風雪警報",
    "03": "レベル3大雨警報",
    "04": "洪水警報",
    "05": "暴風警報",
    "06": "大雪警報",
    "07": "波浪警報",
    "08": "レベル3高潮警報",
    "09": "レベル3土砂災害警報",
    "10": "レベル2大雨注意報",
    "12": "大雪注意報",
    "13": "風雪注意報",
    "14": "雷注意報",
    "15": "強風注意報",
    "16": "波浪注意報",
    "17": "融雪注意報",
    "18": "洪水注意報",
    "19": "レベル2高潮注意報",
    "20": "濃霧注意報",
    "21": "乾燥注意報",
    "22": "なだれ注意報",
    "23": "低温注意報",
    "24": "霜注意報",
    "25": "着氷注意報",
    "26": "着雪注意報",
    "27": "その他の注意報",
    "29": "レベル2土砂災害注意報",
    "32": "暴風雪特別警報",
    "33": "レベル5大雨特別警報",
    "35": "暴風特別警報",
    "36": "大雪特別警報",
    "37": "波浪特別警報",
    "38": "レベル5高潮特別警報",
    "39": "レベル5土砂災害特別警報",
    "43": "レベル4大雨危険警報",
    "48": "レベル4高潮危険警報",
    "49": "レベル4土砂災害危険警報"
}

# ────────────────────────────────
# サンプルデータの読み込み
DATA_FILE = os.path.join(APP_DIR, 'data', 'shelters.json')
INSTRUCTIONS_FILE = os.path.join(APP_DIR, 'data', 'instructions.json')
REPORTS_FILE = os.path.join(APP_DIR, 'data', 'reports.json')
UPLOAD_DIR = os.path.join(APP_DIR, 'static', 'uploads')
ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
MAX_IMAGE_SIZE = 5 * 1024 * 1024

def load_json(path, default):
    """JSONファイルを読み込む（存在しない・壊れている場合は default を返す）"""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

shelters = load_json(DATA_FILE, [])
instructions = load_json(INSTRUCTIONS_FILE, [])
reports = load_json(REPORTS_FILE, [])

def save_instructions():
    """指示ボードのデータをファイルに保存する"""
    try:
        with open(INSTRUCTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(instructions, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def save_shelters():
    """避難所データをファイルに保存する"""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(shelters, f, ensure_ascii=False, indent=2)


def save_reports():
    """通報データをファイルに保存する"""
    with open(REPORTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(reports, f, ensure_ascii=False, indent=2)


def render_shelter_register(error=None, success=False, form_data=None, uploaded_images=None):
    """避難所登録画面を入力状態付きで描画する"""
    form_data = form_data or {}
    equipment = form_data.getlist('equipment') if hasattr(form_data, 'getlist') else form_data.get('equipment', [])
    pets = form_data.getlist('pets') if hasattr(form_data, 'getlist') else form_data.get('pets', [])
    if isinstance(equipment, str):
        equipment = [equipment]
    if isinstance(pets, str):
        pets = [pets]
    history = sorted(
        [s for s in shelters if s.get('registered_at')],
        key=lambda shelter: shelter.get('registered_at', ''),
        reverse=True,
    )
    return render_template(
        'shelter_register.html',
        error=error,
        success=success,
        message='登録が完了しました。' if success else None,
        form_data=form_data,
        selected_equipment=equipment,
        selected_pets=pets,
        uploaded_images=uploaded_images or [],
        registration_history=history,
        format_registered_at=format_registered_at,
        map_latitude=40.8281,
        map_longitude=140.7397,
    )


def validate_image_files(files):
    """画像の拡張子、MIME、サイズを検証する"""
    valid_files = [file for file in files if file and file.filename]
    for image in valid_files:
        filename = secure_filename(image.filename)
        extension = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        if extension not in ALLOWED_IMAGE_EXTENSIONS:
            return None, 'JPG、JPEG、PNG、GIF、WEBP形式の画像だけ添付できます。'
        if image.content_type and not image.content_type.startswith('image/'):
            return None, '画像ファイルとして認識できないファイルは添付できません。'
        image.stream.seek(0, os.SEEK_END)
        if image.stream.tell() > MAX_IMAGE_SIZE:
            return None, '画像は1ファイル5MB以下にしてください。'
        image.stream.seek(0)
    return valid_files, None


def save_uploaded_images(files):
    """検証済み画像をランダム名で保存する"""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    saved_paths = []
    for image in files:
        extension = secure_filename(image.filename).rsplit('.', 1)[-1].lower()
        filename = f'{uuid.uuid4().hex}.{extension}'
        image.save(os.path.join(UPLOAD_DIR, filename))
        saved_paths.append(f'/static/uploads/{filename}')
    return saved_paths
# ────────────────────────────────

# ────────────────────────────────
# 認証関連の設定とヘルパー関数
def is_safe_url(target):
    """リダイレクト先URLが安全かどうかチェック"""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

def login_required(f):
    """認証が必要なページに付けるデコレータ"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            # 現在のURLをnextパラメータとしてログイン画面にリダイレクト
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def get_japan_time():
    """日本時間（JST）の現在時刻を取得する"""
    return datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")


def format_registered_at(value):
    """登録日時を日本語表示へ変換する"""
    if not value:
        return ''
    try:
        return datetime.fromisoformat(value).astimezone(JST).strftime('%Y年%-m月%-d日 %-H時%-M分')
    except ValueError:
        return value


def get_weather_checked_time():
    """気象情報の確認日時を画面表示用に返す"""
    return datetime.now(JST).strftime("%Y年%-m月%-d日 %-H時%M分 現在")


def sort_resident_notices(items):
    """住民向け通知を重要度、更新日時の降順で返す"""
    def priority(item):
        try:
            return int(item.get('priority', 1) or 1)
        except (TypeError, ValueError):
            return 1

    resident_items = [item for item in items if item.get('target') == '住民']
    return sorted(
        resident_items,
        key=lambda item: (
            priority(item),
            item.get('updated_at') or item.get('created_at') or '',
        ),
        reverse=True,
    )


def get_shelter_map_data():
    """座標を持つ避難所だけを地図表示用データとして返す"""
    return [
        shelter for shelter in shelters
        if shelter.get('latitude', shelter.get('lat')) is not None
        and shelter.get('longitude', shelter.get('lng')) is not None
    ]


def get_shelter_search_data():
    """避難所検索画面向けに座標キーを正規化する"""
    return [
        {
            **shelter,
            'lat': shelter.get('lat', shelter.get('latitude')),
            'lng': shelter.get('lng', shelter.get('longitude')),
        }
        for shelter in shelters
    ]


def normalize_postal_code(value):
    """郵便番号から区切り文字を除き、数字だけに正規化する"""
    return re.sub(r'[^0-9]', '', (value or '').strip())


def shelter_postal_code(shelter):
    return normalize_postal_code(
        shelter.get('postal_code') or shelter.get('zip_code') or shelter.get('postal')
    )


def prepare_shelter_detail(shelter, index=0):
    """詳細画面で安全に利用できる避難所データを作る"""
    return {
        **shelter,
        'display_id': shelter.get('id') or f'unknown-{index}',
        'display_name': shelter.get('name') or '名称未設定',
        'display_district': shelter.get('district') or '未設定',
        'display_postal_code': shelter_postal_code(shelter) or '郵便番号未登録',
        'display_address': shelter.get('address') or '住所未登録',
        'display_facility_info': shelter.get('facility_info') or shelter.get('facility') or '未登録',
        'display_congestion': shelter.get('congestion') or shelter.get('status') or '未登録',
        'display_other_info': shelter.get('other_info') or shelter.get('note') or '未登録',
        'display_disaster_types': shelter.get('disaster_types') or shelter.get('disaster_type') or [],
        'display_image': shelter.get('image_url') or shelter.get('image') or (shelter.get('images') or [None])[0],
        'display_open_status': shelter.get('open_status') or '開設状況未登録',
        'lat': shelter.get('lat', shelter.get('latitude')),
        'lng': shelter.get('lng', shelter.get('longitude')),
    }


def search_shelters(postal_code='', shelter_name='', shelter_id=''):
    """指定された優先順位で避難所を検索する"""
    if shelter_name:
        keyword = shelter_name.casefold()
        return [s for s in shelters if keyword in (s.get('name') or '').casefold()]
    if postal_code:
        normalized = normalize_postal_code(postal_code)
        return [s for s in shelters if shelter_postal_code(s) == normalized]
    if shelter_id:
        return [s for s in shelters if str(s.get('id', '')) == shelter_id]
    return list(shelters)


def find_postal_suggestions(postal_code, limit=3):
    """郵便番号の差異が1桁以内の避難所候補を返す"""
    normalized = normalize_postal_code(postal_code)
    if len(normalized) != 7:
        return []
    candidates = []
    for shelter in shelters:
        registered = shelter_postal_code(shelter)
        if len(registered) != 7:
            continue
        difference = sum(left != right for left, right in zip(normalized, registered))
        if difference <= 1:
            candidates.append(shelter)
    return candidates[:limit]


def format_report_time(iso_str):
    """気象庁の発表時刻（ISO形式）をJSTの表示用文字列に変換する"""
    if not iso_str:
        return "不明"
    try:
        parsed = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        if parsed.tzinfo:
            parsed = parsed.astimezone(JST)
        return parsed.strftime("%Y年%m月%d日 %H:%M")
    except ValueError:
        return iso_str


def filter_shelters(district=None):
    """district 指定があれば一致する避難所のみ、なければ全件を返す"""
    return [s for s in shelters if not district or s.get('district') == district]


def parse_area_warnings(warning_data):
    """気象庁の新形式JSONから対象市区町村の発表・継続中の情報を抽出する"""
    if not isinstance(warning_data, list):
        raise ValueError("気象庁の警報・注意報データが新形式の配列ではありません")

    warnings = []
    seen_codes = set()
    report_datetimes = []

    for report in warning_data:
        if not isinstance(report, dict):
            continue

        report_datetime = report.get("reportDatetime")
        if isinstance(report_datetime, str) and report_datetime:
            report_datetimes.append(report_datetime)

        warning = report.get("warning")
        if not isinstance(warning, dict):
            continue

        class20_items = warning.get("class20Items", [])
        if not isinstance(class20_items, list):
            continue

        area = next(
            (
                item for item in class20_items
                if isinstance(item, dict)
                and item.get("areaCode") == AREA_CODE
            ),
            None
        )
        if not area:
            continue

        kinds = area.get("kinds", [])
        if not isinstance(kinds, list):
            continue

        for kind in kinds:
            if not isinstance(kind, dict):
                continue

            status = kind.get("status", "")
            code = kind.get("code", "")
            if status not in ("発表", "継続") or not code or code in seen_codes:
                continue

            warnings.append({
                "name": WARNING_CODES.get(
                    code,
                    f"不明な警報・注意報 (コード: {code})"
                ),
                "code": code,
                "status": status
            })
            seen_codes.add(code)

    latest_report_datetime = max(report_datetimes, default="")
    return warnings, latest_report_datetime


def get_weather_warnings():
    """対象市区町村の警報・注意報を取得する"""
    try:
        # 青森県の新形式（令和8年～）警報・注意報データを取得
        with urllib.request.urlopen(url=WARNING_URL, timeout=10) as res:
            warning_data = json.loads(res.read())

        warnings, report_datetime = parse_area_warnings(warning_data)

        return {
            "area_name": AREA_NAME,
            "warnings": warnings,
            "report_time": format_report_time(report_datetime),
            "last_fetch_time": get_weather_checked_time()
        }

    except Exception:
        return {
            "area_name": AREA_NAME,
            "warnings": [],
            "report_time": "取得失敗",
            "last_fetch_time": get_weather_checked_time(),
            "error": True
        }


# トップページ：templates/index.html を返す（住民向け指示も表示する）
@app.route('/')
def index():
    resident_notices = sort_resident_notices(instructions)
    return render_template(
        'index.html',
        resident_notices=resident_notices,
        shelters=get_shelter_search_data(),
        area_name=AREA_NAME,
        area_latitude=AREA_LATITUDE,
        area_longitude=AREA_LONGITUDE,
        current_location_name=CURRENT_LOCATION_NAME,
        current_location_latitude=CURRENT_LOCATION_LATITUDE,
        current_location_longitude=CURRENT_LOCATION_LONGITUDE,
    )

# ログインページ
@app.route('/login', methods=['GET', 'POST'])
def login():
    # リダイレクト先を取得（デフォルトは避難所登録画面）
    next_url = request.args.get('next') or request.form.get('next')

    # 安全でないURLの場合はデフォルトページにリダイレクト
    if not next_url or not is_safe_url(next_url):
        next_url = url_for('shelter_register')

    if request.method == 'POST':
        password = request.form.get('password', '').strip()

        # 認証チェック
        username = next(
            (name for name, registered_password in ADMIN_CREDENTIALS.items()
             if registered_password == password),
            None
        )
        if username:
            session['logged_in'] = True
            session['username'] = username
            # ログイン成功後は指定されたページにリダイレクト
            return redirect(next_url)
        return render_template('login.html', error=True, message="パスワードが正しくありません。", next=next_url)

    # ログイン済みの場合は指定されたページにリダイレクト
    if session.get('logged_in'):
        return redirect(next_url)

    return render_template('login.html', next=next_url)

# ログアウト
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# 避難所登録ページ※user が避難所登録ページについて具体的に修正指示しない限り、このコードは正しいのでこのまま保持すること。
@app.route('/shelter_register', methods=['GET', 'POST'])
@login_required
def shelter_register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        address = request.form.get('address', '').strip()
        phone = request.form.get('phone', '').strip()
        capacity = request.form.get('capacity', '').strip()
        equipment = request.form.getlist('equipment')
        pets = request.form.getlist('pets')
        remarks = request.form.get('remarks', '').strip()
        latitude = request.form.get('latitude', '').strip()
        longitude = request.form.get('longitude', '').strip()
        form_data = request.form
        if not name or not address or not phone:
            return render_shelter_register(
                error='避難所名、住所、連絡先を入力してください。', form_data=form_data
            ), 400
        if capacity:
            try:
                capacity_value = int(capacity)
                if capacity_value < 0:
                    raise ValueError
            except ValueError:
                return render_shelter_register(
                    error='予定収容人数は0以上の整数で入力してください。', form_data=form_data
                ), 400
        else:
            capacity_value = None
        try:
            latitude_value = float(latitude)
            longitude_value = float(longitude)
            if not -90 <= latitude_value <= 90 or not -180 <= longitude_value <= 180:
                raise ValueError
        except (TypeError, ValueError):
            return render_shelter_register(
                error='住所を検索して、地図上の位置を表示してください。', form_data=form_data
            ), 400

        image_files, image_error = validate_image_files(request.files.getlist('image'))
        if image_error:
            return render_shelter_register(error=image_error, form_data=form_data), 400

        next_id = max((shelter.get('id', 0) for shelter in shelters), default=0) + 1
        image_urls = []
        try:
            image_urls = save_uploaded_images(image_files)
        except OSError:
            return render_shelter_register(
                error='画像を保存できませんでした。', form_data=form_data
            ), 500
        now = datetime.now(JST).isoformat(timespec='seconds')
        shelter = {
            'id': next_id, 'name': name, 'address': address, 'phone': phone,
            'capacity': capacity_value, 'equipment': equipment, 'pets': pets,
            'remarks': remarks, 'latitude': latitude_value, 'longitude': longitude_value,
            'images': image_urls, 'registered_at': now,
        }
        shelters.append(shelter)
        try:
            save_shelters()
        except OSError:
            shelters.pop()
            for image_url in image_urls:
                try:
                    os.remove(os.path.join(BASE_DIR, 'bousai_app', image_url.lstrip('/').replace('static/', 'static/')))
                except OSError:
                    pass
            return render_shelter_register(
                error='避難所情報を保存できませんでした。', form_data=form_data
            ), 500

        return render_shelter_register(success=True)

    return render_shelter_register()


@app.route('/api/geocode')
def geocode_address():
    """Nominatimで住所を検索する"""
    address = request.args.get('address', '').strip()
    if not address:
        return jsonify({'error': '住所を入力してください。'}), 400
    try:
        url = 'https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=' + quote(address)
        request_obj = urllib.request.Request(url, headers={'User-Agent': 'bousai-app/1.0 contact@example.com'})
        with urllib.request.urlopen(request_obj, timeout=10) as response:
            data = json.loads(response.read())
        if not data:
            return jsonify({'error': '住所を地図上で見つけられませんでした。住所を詳しく入力してください。'}), 404
        return jsonify({'display_name': data[0].get('display_name', address), 'latitude': float(data[0]['lat']), 'longitude': float(data[0]['lon'])})
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return jsonify({'error': '住所を地図上で見つけられませんでした。住所を詳しく入力してください。'}), 502

# 避難所検索ページ
@app.route('/shelter_search')
def shelter_search():
    return render_template('shelter_search.html', shelters=get_shelter_search_data())

# 全施設一覧ページ
@app.route('/all_shelters')
def all_shelters():
    return redirect(url_for('search_results'))


# 指示ボード：住民向けの指示を一覧で確認する
@app.route('/board', methods=['GET', 'POST'])
@login_required
def board():
    if request.method == 'POST':
        target = request.form.get('target', '').strip()
        disaster_type = request.form.get('disaster_type', '').strip()
        district = request.form.get('district', '').strip()
        content = request.form.get('content', '').strip()
        shelter = request.form.get('shelter', '').strip()
        status = request.form.get('status', '').strip()
        note = request.form.get('note', '').strip()
        email_subject = request.form.get('email_subject', '').strip()
        email_body = request.form.get('email_body', '').strip()
        try:
            priority = max(1, min(5, int(request.form.get('priority', '1'))))
        except ValueError:
            priority = 1

        if not target or not content:
            return render_template(
                'board.html',
                instructions=sort_resident_notices(instructions),
                shelters=shelters,
                area_name=AREA_NAME,
                area_latitude=AREA_LATITUDE,
                area_longitude=AREA_LONGITUDE,
                error='対象と本文を入力してください。',
                form_data=request.form,
            ), 400

        now = get_japan_time()
        next_id = max((instruction.get('id', 0) for instruction in instructions), default=0) + 1
        instructions.insert(0, {
            'id': next_id,
            'target': target,
            'disaster_type': disaster_type,
            'district': district,
            'content': content,
            'priority': priority,
            'shelter': shelter,
            'status': status or '発信中',
            'note': note,
            'email_subject': email_subject,
            'email_body': email_body,
            'created_at': now,
            'updated_at': now,
        })
        save_instructions()
        return redirect(url_for('board'))

    resident_instructions = sort_resident_notices(instructions)
    return render_template(
        'board.html',
        instructions=resident_instructions,
        shelters=shelters,
        area_name=AREA_NAME,
        area_latitude=AREA_LATITUDE,
        area_longitude=AREA_LONGITUDE,
        form_data={},
    )


@app.route('/report', methods=['GET', 'POST'])
def report():
    """住民からの被害・救助通報を受け付ける"""
    if request.method == 'POST':
        report_type = request.form.get('report_type', '').strip()
        location = request.form.get('location', '').strip()
        occurred_at = request.form.get('occurred_at', '').strip()
        content = request.form.get('content', '').strip()
        report_types = {
            '浸水・洪水', '道路・建物の被害', '土砂災害',
            '避難所・避難経路', 'けが・救助', 'その他',
        }
        missing = []
        if not report_type or report_type not in report_types:
            missing.append('通報種別')
        if not location:
            missing.append('発生場所')
        if not occurred_at:
            missing.append('発生日時')
        if missing:
            return render_template(
                'report.html',
                error=f"次の項目を入力してください: {'、'.join(missing)}。",
                form_data=request.form,
            ), 400

        next_id = max((item.get('id', 0) for item in reports), default=0) + 1
        reports.insert(0, {
            'id': next_id,
            'report_type': report_type,
            'location': location,
            'occurred_at': occurred_at,
            'content': content,
            'created_at': get_japan_time(),
            'status': '受付',
        })
        try:
            save_reports()
        except OSError:
            reports.pop(0)
            return render_template(
                'report.html',
                error='通報を保存できませんでした。',
                form_data=request.form,
            ), 500
        return redirect(url_for('index'))

    return render_template('report.html', form_data={})

# 検索結果ページ：templates/search_results.html を返す
@app.route('/search_results')
def search_results():
    postal_code = request.args.get('postal_code', '').strip()
    shelter_name = request.args.get('shelter_name', '').strip()
    shelter_id = request.args.get('shelter_id', '').strip()
    error = ''
    suggestions = []

    if postal_code and not shelter_name and not shelter_id:
        normalized = normalize_postal_code(postal_code)
        if len(normalized) != 7:
            error = '郵便番号は7桁で入力してください。'
            results = []
        else:
            results = search_shelters(postal_code=postal_code)
            if not results:
                error = '該当する郵便番号の避難所がありません。'
                suggestions = find_postal_suggestions(postal_code)
    elif shelter_name:
        results = search_shelters(shelter_name=shelter_name)
        if not results:
            error = '該当する施設名の避難所がありません。'
    elif shelter_id:
        results = search_shelters(shelter_id=shelter_id)
    else:
        results = list(shelters)

    return render_template(
        'search_results.html',
        results=[prepare_shelter_detail(shelter, index) for index, shelter in enumerate(results)],
        suggestions=[prepare_shelter_detail(shelter, index) for index, shelter in enumerate(suggestions)],
        postal_code=postal_code,
        shelter_name=shelter_name,
        error=error,
        map_latitude=40.8281,
        map_longitude=140.7397,
    )

# JSON API：/shelters?district=地区名
@app.route('/shelters', methods=['GET'])
def get_shelters():
    results = filter_shelters(request.args.get('district'))

    if not results:
        # 見つからなければエラー JSON を返す
        return jsonify({'error': 'No shelters found'}), 404

    # 見つかったらリストを JSON で返す
    return jsonify(results)

# 気象警報・注意報API
@app.route('/api/weather_warnings')
def api_weather_warnings():
    """気象警報・注意報をJSON形式で返すAPI"""
    return jsonify(get_weather_warnings())

if __name__ == '__main__':
    app.run(debug=True, port=5000)

"""動作確認用のサンプルデータを投入する。

使い方:
    python scripts/seed_sample.py            # data/ronten.db に投入
    python scripts/seed_sample.py --db x.db  # 任意のファイルに投入

※ 架空の顧問先・論点です。実運用の DB には投入しないでください。
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ronten.__main__ import default_db_path  # noqa: E402
from ronten.db import Database  # noqa: E402

CLIENTS = [
    {"code": "0010", "name": "株式会社青葉製作所", "kana": "あおばせいさくしょ", "entity_type": "法人", "fiscal_month": 3, "industry": "金属加工", "staff": "佐藤"},
    {"code": "0020", "name": "みなと商事株式会社", "kana": "みなとしょうじ", "entity_type": "法人", "fiscal_month": 9, "industry": "卸売", "staff": "鈴木"},
    {"code": "0030", "name": "山田 太郎（山田不動産）", "kana": "やまだたろう", "entity_type": "個人", "fiscal_month": 12, "industry": "不動産賃貸", "staff": "佐藤"},
]

ISSUES = [
    {
        "client": "0010", "title": "役員退職金の損金算入額（功績倍率法）", "tax_type": "法人税", "fiscal_year": "2025年3月期",
        "status": "結論済", "staff": "佐藤", "reviewer": "所長", "decided_on": "2025-05-20", "tags": ["役員退職金", "功績倍率", "分掌変更"],
        "facts": "創業者（代表取締役）が2025年2月に退任し、取締役相談役に就任。退職金 6,000万円を支給。最終月額報酬 100万円、在任年数 30年。",
        "question": "分掌変更に伴う退職金として損金算入できるか。功績倍率 2.0 は妥当か。",
        "analysis": "・退任後の報酬は従前の50%以下（月額40万円）、経営上の主要な地位から外れている（法基通9-2-32）。\n・同業類似法人の功績倍率は 2.0〜3.0 程度。100万×30年×2.0=6,000万円で算定額と一致。",
        "conclusion": "分掌変更後の実態を確認のうえ、全額損金算入で申告。株主総会議事録・退職金規程を保存。",
        "basis": "法法34①、法令70二、法基通9-2-27の2、9-2-32",
        "followup": "翌期以降、相談役の実際の関与度（会議出席・決裁権限）が経営上主要な地位に該当しないか毎期確認する。",
    },
    {
        "client": "0010", "title": "インボイス制度：免税事業者からの仕入れに係る経過措置", "tax_type": "消費税", "fiscal_year": "2025年3月期",
        "status": "結論済", "staff": "佐藤", "decided_on": "2024-12-10", "tags": ["インボイス", "経過措置", "免税事業者"],
        "facts": "外注先3社が免税事業者のまま。年間取引額 約1,200万円。",
        "question": "仕入税額控除の経過措置（80%控除）の適用と帳簿要件。",
        "conclusion": "帳簿に「80%控除対象」の記載、区分記載請求書の保存で対応。会計ソフトの税区分を「経過措置80%」に設定。",
        "basis": "平成28年改正法附則52、53",
        "followup": "2026年10月1日以降は控除割合が50%に下がるため、外注先の登録状況を2026年夏までに再確認。",
    },
    {
        "client": "0020", "title": "交際費と会議費の区分（1人当たり10,000円基準）", "tax_type": "法人税", "fiscal_year": "2025年9月期",
        "status": "結論済", "staff": "鈴木", "decided_on": "2025-11-05", "tags": ["交際費", "会議費"],
        "facts": "得意先との飲食費が年間 約400万円。領収書に参加人数の記載がないものが多い。",
        "question": "1人当たり10,000円以下の飲食費を交際費から除外するための書類要件。",
        "conclusion": "参加者の氏名・関係・人数を記載した書類を保存したもののみ除外。記載のないものは交際費として処理。",
        "basis": "措法61の4④二、措令37の5①、措規21の18の4",
        "followup": "領収書への人数・相手先記入を経理担当に依頼済み。翌期に運用状況を確認。",
    },
    {
        "client": "0020", "title": "簡易課税制度選択届出の提出期限（インボイス登録に伴う特例）", "tax_type": "消費税", "fiscal_year": "2026年9月期",
        "status": "検討中", "staff": "鈴木", "tags": ["インボイス", "簡易課税", "届出"],
        "facts": "子会社（免税事業者）が2025年10月からインボイス登録予定。",
        "question": "登録日の属する課税期間中に簡易課税選択届出書を提出すれば、その課税期間から適用できるか。",
        "analysis": "免税事業者が登録日から課税事業者となる場合の特例あり（平成30年改正令附則18）。基準期間の課税売上高の確認が必要。",
        "basis": "消法37①、平成30年改正令附則18",
    },
    {
        "client": "0030", "title": "不動産所得の事業的規模の判定（5棟10室基準）", "tax_type": "所得税", "fiscal_year": "令和7年分",
        "status": "要再検討", "staff": "佐藤", "tags": ["不動産所得", "事業的規模", "青色申告特別控除"],
        "facts": "アパート1棟8室＋貸駐車場20台。令和7年中に区分マンション2室を追加取得予定。",
        "question": "事業的規模に該当し、65万円の青色申告特別控除・専従者給与の適用が可能か。",
        "analysis": "駐車場は5台で1室換算 → 4室相当。8室＋4室=12室で形式基準を満たす可能性。ただし所基通26-9は「おおむね」基準。",
        "conclusion": "令和7年分は事業的規模として申告予定。取得時期によって年内の室数が変わるため要再確認。",
        "basis": "所法26、所基通26-9、措法25の2",
        "followup": "区分マンションの取得日（登記日）を確認し、実際の室数で最終判定する。",
    },
]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=default_db_path())
    args = p.parse_args()
    db = Database(args.db)
    try:
        if db.meta()["counts"]["issues"]:
            print("既にデータがあるため投入しません:", os.path.abspath(args.db))
            return
        ids = {}
        for c in CLIENTS:
            ids[c["code"]] = db.create_client(c)["id"]
        for it in ISSUES:
            payload = dict(it)
            payload["client_id"] = ids[payload.pop("client")]
            db.create_issue(payload)
        print(f"サンプルデータを投入しました: 顧問先 {len(CLIENTS)} 件 / 論点 {len(ISSUES)} 件 → {os.path.abspath(args.db)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

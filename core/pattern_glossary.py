"""Formasyon sozlugu: her formasyonun ne anlama geldigi, nasil teyit edildigi ve nerede gecersiz oldugu.

Kullanici bir sinyale tikladiginda gosterilir. Metinler klasik teknik analiz
tanimlaridir; **tahmin degil, kosullu beklentidir**.

ONEMLI: `ai_modules/pattern_rules.py` formasyonun **sekline** bakar; kirilimin
gerceklestigini dogrulamaz. Yani sistem "formasyon olustu" der, "hareket basladi"
demez. Her kayittaki `confirmation` alani, kullanicinin kendi gozuyle aramasi
gereken teyidi anlatir.
"""

from __future__ import annotations

from schemas.signal import Direction, Pattern, PatternInfo

DISCLAIMER = (
    "Bu aciklama egitim amaclidir, yatirim tavsiyesi degildir. Formasyonlar garanti "
    "vermez; teyit gelmeden yon degistirebilir ve sik sik basarisiz olur."
)

# Sistemin tespit ettigi sey ile kullanicinin beklemesi gereken sey arasindaki fark
DETECTION_CAVEAT = (
    "Sistem formasyonun **seklini** tespit etti; kirilimin gerceklestigini dogrulamadi. "
    "Teyit kosulu saglanmadan formasyon henuz calismis sayilmaz."
)

_GLOSSARY: dict[Pattern, PatternInfo] = {
    Pattern.DOUBLE_TOP: PatternInfo(
        pattern=Pattern.DOUBLE_TOP,
        label="Cift Tepe",
        direction=Direction.SHORT,
        family="donus",
        summary="Yukselis trendi ayni seviyede iki kez reddedildi; satici baskisi belirginlesiyor.",
        forms=(
            "Fiyat bir zirveye cikar, geri cekilir, tekrar ayni seviyeye yukselir ama "
            "gecemez. Iki tepe birbirine yakin (sistemde %3 tolerans), aralarindaki "
            "dip belirgin (en az %3 derinlik)."
        ),
        implication=(
            "Alicilar ayni direnci iki kez kiramadi. Klasik beklenti asagi yon: iki tepe "
            "arasindaki dip (boyun cizgisi) kirilirsa dusus surebilir."
        ),
        confirmation=(
            "Fiyatin iki tepe arasindaki dip seviyesinin ALTINDA kapanmasi. "
            "Kirilima hacim artisi eslik ederse guvenilirlik artar."
        ),
        invalidation=(
            "Fiyat tepe seviyesinin uzerinde kapanirsa formasyon gecersizdir; "
            "bu genelde yukselisin devami anlamina gelir."
        ),
        target=(
            "Olcum kurali: tepe ile boyun cizgisi arasindaki mesafe, kirilim noktasindan "
            "asagi dogru projekte edilir."
        ),
        pitfalls=(
            "En sik hata, ikinci tepe olustugu anda satmaktir. Boyun cizgisi kirilmadan "
            "formasyon tamamlanmis sayilmaz; yatay seyir aylarca surebilir."
        ),
    ),
    Pattern.DOUBLE_BOTTOM: PatternInfo(
        pattern=Pattern.DOUBLE_BOTTOM,
        label="Cift Dip",
        direction=Direction.LONG,
        family="donus",
        summary="Dusus ayni seviyede iki kez durduruldu; alici ilgisi olusuyor.",
        forms=(
            "Fiyat bir dibe iner, toparlanir, tekrar ayni seviyeye geriler ama altina "
            "inmez. Iki dip birbirine yakin, aralarindaki tepe belirgin."
        ),
        implication=(
            "Satis baskisi ayni seviyede iki kez emildi. Klasik beklenti yukari yon: "
            "iki dip arasindaki tepe (boyun cizgisi) asilirsa yukselis surebilir."
        ),
        confirmation=(
            "Fiyatin iki dip arasindaki tepe seviyesinin USTUNDE kapanmasi; "
            "kirilimda hacim artisi tercih edilir."
        ),
        invalidation="Fiyat dip seviyesinin altinda kapanirsa formasyon gecersizdir.",
        target="Dip ile boyun cizgisi arasindaki mesafe, kirilimdan yukari projekte edilir.",
        pitfalls=(
            "Dusen bicak yakalama riski: dip henuz test edilmemisken alim yapmak. "
            "Boyun cizgisi kirilimi beklenmezse ucuncu bir dip gelebilir."
        ),
    ),
    Pattern.HEAD_SHOULDERS: PatternInfo(
        pattern=Pattern.HEAD_SHOULDERS,
        label="Omuz Bas Omuz",
        direction=Direction.SHORT,
        family="donus",
        summary="Yukselisin gucu tukeniyor: her tepe bir oncekini asamiyor.",
        forms=(
            "Uc tepe olusur; ortadaki (bas) en yuksek, yanlardakiler (omuzlar) birbirine "
            "yakin ve daha alcak. Iki dibi birlestiren cizgi boyun cizgisidir."
        ),
        implication=(
            "Trendin ivmesi kayboldu; alicilar son yuksegi tekrarlayamiyor. "
            "Klasik beklenti asagi yon."
        ),
        confirmation=(
            "Boyun cizgisinin ALTINDA kapanis. Kirilim sonrasi fiyatin boyun cizgisini "
            "asagidan test edip reddedilmesi (geri donus) ek teyit sayilir."
        ),
        invalidation="Sag omuz basi asarsa formasyon bozulur.",
        target="Bas ile boyun cizgisi arasindaki dikey mesafe, kirilimdan asagi projekte edilir.",
        pitfalls=(
            "Boyun cizgisi her zaman yatay degildir; egimli boyun cizgilerinde kirilim "
            "seviyesi tartismalidir ve yanlis sinyal orani artar."
        ),
    ),
    Pattern.INV_HEAD_SHOULDERS: PatternInfo(
        pattern=Pattern.INV_HEAD_SHOULDERS,
        label="Ters Omuz Bas Omuz",
        direction=Direction.LONG,
        family="donus",
        summary="Dususun gucu tukeniyor: her dip bir oncekinden daha sig.",
        forms=(
            "Uc dip olusur; ortadaki (bas) en derin, yanlardakiler daha sig ve birbirine "
            "yakin. Iki tepeyi birlestiren cizgi boyun cizgisidir."
        ),
        implication="Satis baskisi zayifliyor. Klasik beklenti yukari yon.",
        confirmation=(
            "Boyun cizgisinin USTUNDE kapanis; kirilimda hacim artisi guvenilirligi yukseltir."
        ),
        invalidation="Sag omuz basin altina inerse formasyon bozulur.",
        target="Bas ile boyun cizgisi arasindaki mesafe, kirilimdan yukari projekte edilir.",
        pitfalls=(
            "Dusus trendinin ortasinda benzer sekiller sik gorulur; trendin uzun sureli "
            "oldugu ve hacmin daraldigi durumlarda daha anlamlidir."
        ),
    ),
    Pattern.ASC_TRIANGLE: PatternInfo(
        pattern=Pattern.ASC_TRIANGLE,
        label="Yukselen Ucgen",
        direction=Direction.LONG,
        family="devam",
        summary="Direnc sabit, dipler yukseliyor: alicilar her seferinde daha erken giriyor.",
        forms=(
            "Ustte yatay bir direnc seviyesi, altta yukselen bir destek cizgisi. "
            "Fiyat sikisarak ucgenin ucuna dogru ilerler."
        ),
        implication=(
            "Alicilar sabirsizlaniyor, saticilar ayni seviyede sabit. Sikisma cozuldugunde "
            "klasik beklenti yukari yon."
        ),
        confirmation="Yatay direncin USTUNDE kapanis; hacim artisi beklenir.",
        invalidation="Yukselen destek cizgisinin altina sarkma formasyonu bozar.",
        target="Ucgenin en genis yerindeki dikey mesafe, kirilimdan yukari projekte edilir.",
        pitfalls=(
            "Ucgenin ucuna cok yaklasmis kirilimlar zayiftir; ideal kirilim ucgenin "
            "yaklasik %60-75'lik bolumunde gerceklesir."
        ),
    ),
    Pattern.DESC_TRIANGLE: PatternInfo(
        pattern=Pattern.DESC_TRIANGLE,
        label="Alcalan Ucgen",
        direction=Direction.SHORT,
        family="devam",
        summary="Destek sabit, tepeler alcaliyor: saticilar her seferinde daha erken satiyor.",
        forms=(
            "Altta yatay bir destek seviyesi, ustte alcalan bir direnc cizgisi. "
            "Fiyat sikisarak ucgenin ucuna ilerler."
        ),
        implication=(
            "Alicilar geri cekiliyor, destek her testte zayifliyor. Klasik beklenti asagi yon."
        ),
        confirmation="Yatay destegin ALTINDA kapanis.",
        invalidation="Alcalan direnc cizgisinin uzerinde kapanis formasyonu bozar.",
        target="Ucgenin en genis yerindeki mesafe, kirilimdan asagi projekte edilir.",
        pitfalls=(
            "Guclu yukselis trendlerinde alcalan ucgen bazen yukari kirilir; "
            "formasyonun yonu trendden bagimsiz dusunulmemelidir."
        ),
    ),
    Pattern.BULL_FLAG: PatternInfo(
        pattern=Pattern.BULL_FLAG,
        label="Boga Bayragi",
        direction=Direction.LONG,
        family="devam",
        summary="Sert yukselisten sonra kisa bir dinlenme; trendin devami beklenir.",
        forms=(
            "Once dik bir yukselis (bayrak diregi), ardindan hafif asagi egimli dar bir "
            "kanal icinde kar satisi. Duzeltme sig ve kisa surelidir."
        ),
        implication=(
            "Yukselis trendi kirilmadi, yalnizca nefeslendi. Klasik beklenti yukari yon."
        ),
        confirmation="Bayrak kanalinin ust sinirinin USTUNDE kapanis.",
        invalidation=(
            "Duzeltme bayrak diregi yukselisinin yarisindan fazlasini geri alirsa "
            "formasyon bayrak olmaktan cikar."
        ),
        target="Bayrak diregi boyu, kirilim noktasindan yukari projekte edilir.",
        pitfalls=(
            "Uzayan bayraklar guvenilirligini kaybeder; dinlenme birkac mumdan cok "
            "surerse trend donusune donusebilir."
        ),
    ),
    Pattern.BEAR_FLAG: PatternInfo(
        pattern=Pattern.BEAR_FLAG,
        label="Ayi Bayragi",
        direction=Direction.SHORT,
        family="devam",
        summary="Sert dususten sonra kisa bir toparlanma; dususun devami beklenir.",
        forms=(
            "Once dik bir dusus, ardindan hafif yukari egimli dar bir kanal icinde "
            "tepki alimi."
        ),
        implication="Dusus trendi kirilmadi. Klasik beklenti asagi yon.",
        confirmation="Bayrak kanalinin alt sinirinin ALTINDA kapanis.",
        invalidation="Tepki, dusus hareketinin yarisindan fazlasini geri alirsa formasyon bozulur.",
        target="Dusus hareketinin boyu, kirilimdan asagi projekte edilir.",
        pitfalls=(
            "Dip arayisinda ayi bayragi ile cift dip karistirilir; ayirt edici olan "
            "toparlanmanin sigligidir."
        ),
    ),
    Pattern.CUP_HANDLE: PatternInfo(
        pattern=Pattern.CUP_HANDLE,
        label="Fincan Kulp",
        direction=Direction.LONG,
        family="devam",
        summary="Uzun ve yumusak bir taban olusumu, ardindan kisa bir son sarsintI.",
        forms=(
            "Once U seklinde genis ve yuvarlak bir taban (fincan), sonra fincanin sag "
            "kenarindan kucuk bir geri cekilme (kulp). Kulp fincanin ust yarisinda kalir."
        ),
        implication=(
            "Uzun sureli satis baskisi emildi, son zayif eller kulpta temizlendi. "
            "Klasik beklenti yukari yon."
        ),
        confirmation="Kulpun ust sinirinin (fincan agzi) USTUNDE kapanis.",
        invalidation="Kulp fincanin alt yarisina inerse formasyon bozulur.",
        target="Fincan derinligi, kirilim noktasindan yukari projekte edilir.",
        pitfalls=(
            "En cok zaman isteyen formasyondur; kisa periyotlarda (1h) olusan 'fincanlar' "
            "cogu zaman rastlantidir. Gunluk ve haftalik grafiklerde daha anlamlidir."
        ),
    ),
}


def get_info(pattern: Pattern | str) -> PatternInfo:
    """Formasyon aciklamasini dondurur; bilinmeyen deger icin KeyError."""
    key = pattern if isinstance(pattern, Pattern) else Pattern(str(pattern).strip().lower())
    return _GLOSSARY[key]


def get_info_safe(pattern: Pattern | str) -> PatternInfo | None:
    """Bilinmeyen formasyonda None doner; UI akisini dusurmez (K-03)."""
    try:
        return get_info(pattern)
    except (KeyError, ValueError):
        return None


def all_info() -> list[PatternInfo]:
    """Tum formasyonlar, Pattern enum sirasinda."""
    return [_GLOSSARY[pattern] for pattern in Pattern]


def short_meaning(pattern: Pattern | str) -> str:
    """Bildirim govdesine eklenen tek satirlik ozet."""
    info = get_info_safe(pattern)
    return info.summary if info else ""

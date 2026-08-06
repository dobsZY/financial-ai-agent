"""Formasyon sözlüğü: her formasyonun ne anlama geldiği, nasıl teyit edildiği ve nerede geçersiz olduğu.

Kullanıcı bir sinyale tıkladığında gösterilir. Metinler klasik teknik analiz
tanımlarıdır; **tahmin değil, koşullu beklentidir**.

ÖNEMLİ: `ai_modules/pattern_rules.py` formasyonun **şekline** bakar; kırılımın
gerçekleştiğini doğrulamaz. Yani sistem "formasyon oluştu" der, "hareket başladı"
demez. Her kayıttaki `confirmation` alanı, kullanıcının kendi gözüyle araması
gereken teyidi anlatır.
"""

from __future__ import annotations

from schemas.signal import Direction, Pattern, PatternInfo

DISCLAIMER = (
    "Bu açıklama eğitim amaçlıdır, yatırım tavsiyesi değildir. Formasyonlar garanti "
    "vermez; teyit gelmeden yön değiştirebilir ve sık sık başarısız olur."
)

# Sistemin tespit ettiği şey ile kullanıcının beklemesi gereken şey arasındaki fark
DETECTION_CAVEAT = (
    "Sistem formasyonun şeklini tespit etti; kırılımın gerçekleştiğini doğrulamadı. "
    "Teyit koşulu sağlanmadan formasyon henüz çalışmış sayılmaz."
)

_GLOSSARY: dict[Pattern, PatternInfo] = {
    Pattern.DOUBLE_TOP: PatternInfo(
        pattern=Pattern.DOUBLE_TOP,
        label="Çift Tepe",
        direction=Direction.SHORT,
        family="dönüş",
        summary="Yükseliş trendi aynı seviyede iki kez reddedildi; satıcı baskısı belirginleşiyor.",
        forms=(
            "Fiyat bir zirveye çıkar, geri çekilir, tekrar aynı seviyeye yükselir ama "
            "geçemez. İki tepe birbirine yakındır (sistemde %3 tolerans), aralarındaki "
            "dip belirgindir (en az %3 derinlik)."
        ),
        implication=(
            "Alıcılar aynı direnci iki kez kıramadı. Klasik beklenti aşağı yön: iki tepe "
            "arasındaki dip (boyun çizgisi) kırılırsa düşüş sürebilir."
        ),
        confirmation=(
            "Fiyatın iki tepe arasındaki dip seviyesinin ALTINDA kapanması. "
            "Kırılıma hacim artışı eşlik ederse güvenilirlik artar."
        ),
        invalidation=(
            "Fiyat tepe seviyesinin üzerinde kapanırsa formasyon geçersizdir; "
            "bu genelde yükselişin devamı anlamına gelir."
        ),
        target=(
            "Ölçüm kuralı: tepe ile boyun çizgisi arasındaki mesafe, kırılım noktasından "
            "aşağı doğru projekte edilir."
        ),
        pitfalls=(
            "En sık hata, ikinci tepe oluştuğu anda satmaktır. Boyun çizgisi kırılmadan "
            "formasyon tamamlanmış sayılmaz; yatay seyir aylarca sürebilir."
        ),
    ),
    Pattern.DOUBLE_BOTTOM: PatternInfo(
        pattern=Pattern.DOUBLE_BOTTOM,
        label="Çift Dip",
        direction=Direction.LONG,
        family="dönüş",
        summary="Düşüş aynı seviyede iki kez durduruldu; alıcı ilgisi oluşuyor.",
        forms=(
            "Fiyat bir dibe iner, toparlanır, tekrar aynı seviyeye geriler ama altına "
            "inmez. İki dip birbirine yakın, aralarındaki tepe belirgindir."
        ),
        implication=(
            "Satış baskısı aynı seviyede iki kez emildi. Klasik beklenti yukarı yön: "
            "iki dip arasındaki tepe (boyun çizgisi) aşılırsa yükseliş sürebilir."
        ),
        confirmation=(
            "Fiyatın iki dip arasındaki tepe seviyesinin ÜSTÜNDE kapanması; "
            "kırılımda hacim artışı tercih edilir."
        ),
        invalidation="Fiyat dip seviyesinin altında kapanırsa formasyon geçersizdir.",
        target="Dip ile boyun çizgisi arasındaki mesafe, kırılımdan yukarı projekte edilir.",
        pitfalls=(
            "Düşen bıçak yakalama riski: dip henüz test edilmemişken alım yapmak. "
            "Boyun çizgisi kırılımı beklenmezse üçüncü bir dip gelebilir."
        ),
    ),
    Pattern.HEAD_SHOULDERS: PatternInfo(
        pattern=Pattern.HEAD_SHOULDERS,
        label="Omuz Baş Omuz",
        direction=Direction.SHORT,
        family="dönüş",
        summary="Yükselişin gücü tükeniyor: her tepe bir öncekini aşamıyor.",
        forms=(
            "Üç tepe oluşur; ortadaki (baş) en yüksek, yanlardakiler (omuzlar) birbirine "
            "yakın ve daha alçaktır. İki dibi birleştiren çizgi boyun çizgisidir."
        ),
        implication=(
            "Trendin ivmesi kayboldu; alıcılar son yükseği tekrarlayamıyor. "
            "Klasik beklenti aşağı yön."
        ),
        confirmation=(
            "Boyun çizgisinin ALTINDA kapanış. Kırılım sonrası fiyatın boyun çizgisini "
            "aşağıdan test edip reddedilmesi (geri dönüş) ek teyit sayılır."
        ),
        invalidation="Sağ omuz başı aşarsa formasyon bozulur.",
        target="Baş ile boyun çizgisi arasındaki dikey mesafe, kırılımdan aşağı projekte edilir.",
        pitfalls=(
            "Boyun çizgisi her zaman yatay değildir; eğimli boyun çizgilerinde kırılım "
            "seviyesi tartışmalıdır ve yanlış sinyal oranı artar."
        ),
    ),
    Pattern.INV_HEAD_SHOULDERS: PatternInfo(
        pattern=Pattern.INV_HEAD_SHOULDERS,
        label="Ters Omuz Baş Omuz",
        direction=Direction.LONG,
        family="dönüş",
        summary="Düşüşün gücü tükeniyor: her dip bir öncekinden daha sığ.",
        forms=(
            "Üç dip oluşur; ortadaki (baş) en derin, yanlardakiler daha sığ ve birbirine "
            "yakındır. İki tepeyi birleştiren çizgi boyun çizgisidir."
        ),
        implication="Satış baskısı zayıflıyor. Klasik beklenti yukarı yön.",
        confirmation=(
            "Boyun çizgisinin ÜSTÜNDE kapanış; kırılımda hacim artışı güvenilirliği yükseltir."
        ),
        invalidation="Sağ omuz başın altına inerse formasyon bozulur.",
        target="Baş ile boyun çizgisi arasındaki mesafe, kırılımdan yukarı projekte edilir.",
        pitfalls=(
            "Düşüş trendinin ortasında benzer şekiller sık görülür; trendin uzun süreli "
            "olduğu ve hacmin daraldığı durumlarda daha anlamlıdır."
        ),
    ),
    Pattern.ASC_TRIANGLE: PatternInfo(
        pattern=Pattern.ASC_TRIANGLE,
        label="Yükselen Üçgen",
        direction=Direction.LONG,
        family="devam",
        summary="Direnç sabit, dipler yükseliyor: alıcılar her seferinde daha erken giriyor.",
        forms=(
            "Üstte yatay bir direnç seviyesi, altta yükselen bir destek çizgisi vardır. "
            "Fiyat sıkışarak üçgenin ucuna doğru ilerler."
        ),
        implication=(
            "Alıcılar sabırsızlanıyor, satıcılar aynı seviyede sabit. Sıkışma çözüldüğünde "
            "klasik beklenti yukarı yön."
        ),
        confirmation="Yatay direncin ÜSTÜNDE kapanış; hacim artışı beklenir.",
        invalidation="Yükselen destek çizgisinin altına sarkma formasyonu bozar.",
        target="Üçgenin en geniş yerindeki dikey mesafe, kırılımdan yukarı projekte edilir.",
        pitfalls=(
            "Üçgenin ucuna çok yaklaşmış kırılımlar zayıftır; ideal kırılım üçgenin "
            "yaklaşık %60-75'lik bölümünde gerçekleşir."
        ),
    ),
    Pattern.DESC_TRIANGLE: PatternInfo(
        pattern=Pattern.DESC_TRIANGLE,
        label="Alçalan Üçgen",
        direction=Direction.SHORT,
        family="devam",
        summary="Destek sabit, tepeler alçalıyor: satıcılar her seferinde daha erken satıyor.",
        forms=(
            "Altta yatay bir destek seviyesi, üstte alçalan bir direnç çizgisi vardır. "
            "Fiyat sıkışarak üçgenin ucuna ilerler."
        ),
        implication=(
            "Alıcılar geri çekiliyor, destek her testte zayıflıyor. Klasik beklenti aşağı yön."
        ),
        confirmation="Yatay desteğin ALTINDA kapanış.",
        invalidation="Alçalan direnç çizgisinin üzerinde kapanış formasyonu bozar.",
        target="Üçgenin en geniş yerindeki mesafe, kırılımdan aşağı projekte edilir.",
        pitfalls=(
            "Güçlü yükseliş trendlerinde alçalan üçgen bazen yukarı kırılır; "
            "formasyonun yönü trendden bağımsız düşünülmemelidir."
        ),
    ),
    Pattern.BULL_FLAG: PatternInfo(
        pattern=Pattern.BULL_FLAG,
        label="Boğa Bayrağı",
        direction=Direction.LONG,
        family="devam",
        summary="Sert yükselişten sonra kısa bir dinlenme; trendin devamı beklenir.",
        forms=(
            "Önce dik bir yükseliş (bayrak direği), ardından hafif aşağı eğimli dar bir "
            "kanal içinde kâr satışı görülür. Düzeltme sığ ve kısa sürelidir."
        ),
        implication=(
            "Yükseliş trendi kırılmadı, yalnızca nefeslendi. Klasik beklenti yukarı yön."
        ),
        confirmation="Bayrak kanalının üst sınırının ÜSTÜNDE kapanış.",
        invalidation=(
            "Düzeltme, bayrak direği yükselişinin yarısından fazlasını geri alırsa "
            "formasyon bayrak olmaktan çıkar."
        ),
        target="Bayrak direği boyu, kırılım noktasından yukarı projekte edilir.",
        pitfalls=(
            "Uzayan bayraklar güvenilirliğini kaybeder; dinlenme birkaç mumdan çok "
            "sürerse trend dönüşüne dönüşebilir."
        ),
    ),
    Pattern.BEAR_FLAG: PatternInfo(
        pattern=Pattern.BEAR_FLAG,
        label="Ayı Bayrağı",
        direction=Direction.SHORT,
        family="devam",
        summary="Sert düşüşten sonra kısa bir toparlanma; düşüşün devamı beklenir.",
        forms=(
            "Önce dik bir düşüş, ardından hafif yukarı eğimli dar bir kanal içinde "
            "tepki alımı görülür."
        ),
        implication="Düşüş trendi kırılmadı. Klasik beklenti aşağı yön.",
        confirmation="Bayrak kanalının alt sınırının ALTINDA kapanış.",
        invalidation="Tepki, düşüş hareketinin yarısından fazlasını geri alırsa formasyon bozulur.",
        target="Düşüş hareketinin boyu, kırılımdan aşağı projekte edilir.",
        pitfalls=(
            "Dip arayışında ayı bayrağı ile çift dip karıştırılır; ayırt edici olan "
            "toparlanmanın sığlığıdır."
        ),
    ),
    Pattern.CUP_HANDLE: PatternInfo(
        pattern=Pattern.CUP_HANDLE,
        label="Fincan Kulp",
        direction=Direction.LONG,
        family="devam",
        summary="Uzun ve yumuşak bir taban oluşumu, ardından kısa bir son sarsıntı.",
        forms=(
            "Önce U şeklinde geniş ve yuvarlak bir taban (fincan), sonra fincanın sağ "
            "kenarından küçük bir geri çekilme (kulp) oluşur. Kulp fincanın üst yarısında kalır."
        ),
        implication=(
            "Uzun süreli satış baskısı emildi, son zayıf eller kulpta temizlendi. "
            "Klasik beklenti yukarı yön."
        ),
        confirmation="Kulpun üst sınırının (fincan ağzı) ÜSTÜNDE kapanış.",
        invalidation="Kulp fincanın alt yarısına inerse formasyon bozulur.",
        target="Fincan derinliği, kırılım noktasından yukarı projekte edilir.",
        pitfalls=(
            "En çok zaman isteyen formasyondur; kısa periyotlarda (1h) oluşan 'fincanlar' "
            "çoğu zaman rastlantıdır. Günlük ve haftalık grafiklerde daha anlamlıdır."
        ),
    ),
}


def get_info(pattern: Pattern | str) -> PatternInfo:
    """Formasyon açıklamasını döndürür; bilinmeyen değer için KeyError."""
    key = pattern if isinstance(pattern, Pattern) else Pattern(str(pattern).strip().lower())
    return _GLOSSARY[key]


def get_info_safe(pattern: Pattern | str) -> PatternInfo | None:
    """Bilinmeyen formasyonda None döner; UI akışını düşürmez (K-03)."""
    try:
        return get_info(pattern)
    except (KeyError, ValueError):
        return None


def all_info() -> list[PatternInfo]:
    """Tüm formasyonlar, Pattern enum sırasında."""
    return [_GLOSSARY[pattern] for pattern in Pattern]


def short_meaning(pattern: Pattern | str) -> str:
    """Bildirim gövdesine eklenen tek satırlık özet."""
    info = get_info_safe(pattern)
    return info.summary if info else ""

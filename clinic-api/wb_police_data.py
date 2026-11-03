"""Police stations of Kolkata and the districts around it, as the owner listed them (owner, 2026-11-04: "use these" -- Patuli was missing and a loose sound-alike stored it as Chinsurah).

Source: the owner's own list (Kolkata Police Commissionerate by division, Howrah, Hooghly, North and South 24 Parganas police districts). One line per station:
    Bengali name | English name [| other Latin spellings, "/"-joined]
Women's and cyber-crime stations are left out: they serve a whole division and are never an address's station. Coastal stations are kept.
A station that the older geo_data already holds (matched by its English name) only gains the Bengali spelling; nothing is ever deleted or overwritten
(clinic-api/geo_service.seed_police_lists).
"""

from __future__ import annotations

_KOLKATA = """
মুচিপাড়া|Muchipara
গিরিশ পার্ক|Girish Park
তালতলা|Taltala
পোস্তা|Posta
নিউ মার্কেট|New Market
জোড়াসাঁকো|Jorasanko
হেয়ার স্ট্রিট|Hare Street
বড়বাজার|Burrabazar|Burra Bazar/Barabazar
বউবাজার|Bowbazar|Bow Bazar/Boubazar
টালা|Tala
সিঁথি|Sinthee|Sinthi/Sithi
শ্যামপুকুর|Shyampukur
জোড়াবাগান|Jorabagan
কাশীপুর|Cossipore|Kashipur/Cossipur
চিৎপুর|Chitpur
বটতলা|Burtolla|Bartala/Battala
আমহার্স্ট স্ট্রিট|Amherst Street|Amherst Strit/Amhast Street
ওয়েস্ট পোর্ট|West Port
ওয়াটগঞ্জ|Watgunge|Watgunj/Wattganj
সাউথ পোর্ট|South Port
রাজাবাগান|Rajabagan
নর্থ পোর্ট|North Port
নাদিয়াল|Nadial|Nodial
মেটিয়াবুরুজ|Metiabruz|Metiabruj
গার্ডেনরিচ|Garden Reach|Gardenreach
একবালপুর|Ekbalpur
টালিগঞ্জ|Tollygunge|Tollygunj/Tolly Gunge
শেক্সপিয়র সরণি|Shakespeare Sarani|Shakespeare Sarini
পার্ক স্ট্রিট|Park Street
নিউ আলিপুর|New Alipore
ময়দান|Maidan|Moidan
কালীঘাট|Kalighat|Kali Ghat
হেস্টিংস|Hastings
চেতলা|Chetla
চারু মার্কেট|Charu Market
ভবানীপুর|Bhowanipur|Bhawanipur/Bhabanipur
আলিপুর|Alipore
তপসিয়া|Topsia
তিলজলা|Tiljala
রবীন্দ্র সরোবর|Rabindra Sarobar|Rabindra Sarovar
লেক|Lake
করেয়া|Karaya|Karaiya
গড়িয়াহাট|Gariahat|Gariyahat
বেনিয়াপুকুর|Beniapukur
বালিগঞ্জ|Ballygunge|Balligunj/Baligunge
কসবা|Kasba
রিজেন্ট পার্ক|Regent Park
পাটুলি|Patuli|Patulee
নেতাজিনগর|Netaji Nagar|Netajinagar
যাদবপুর|Jadavpur|Jadabpur
গল্ফ গ্রিন|Golf Green
গড়ফা|Garfa|Garfaa
বাঁশদ্রোণী|Bansdroni|Bansdroni/Bashdroni
ঠাকুরপুকুর|Thakurpukur
তারাতলা|Taratala
সরশুনা|Sarsuna|Sarshuna
পর্ণশ্রী|Parnasree|Parnashree
হরিদেবপুর|Haridevpur
বেহালা|Behala
সার্ভে পার্ক|Survey Park
পূর্ব যাদবপুর|Purba Jadavpur|East Jadavpur
প্রগতি ময়দান|Pragati Maidan
পঞ্চসায়র|Panchasayar|Panchasayer
কলকাতা লেদার কমপ্লেক্স|Kolkata Leather Complex|Leather Complex
আনন্দপুর|Anandapur
উল্টোডাঙা|Ultadanga|Ultadanga/Ultodanga
ট্যাংরা|Tangra|Tengra
ফুলবাগান|Phoolbagan|Fulbagan
নারকেলডাঙা|Narkeldanga
মানিকতলা|Manicktala|Maniktala
এন্টালি|Entally
বেলেঘাটা|Beliaghata|Beleghata/Baliaghata
"""

_BHANGAR = """
বোদড়া|Bodra
মাধবপুর|Madhabpur
বিজয়গঞ্জ বাজার|Bijoygunj Bazar
হাতিশালা|Hatisala
উত্তর কাশীপুর|Uttar Kashipur
ভাঙড়|Bhangar
চন্দনেশ্বর|Chandaneswar
পোলেরহাট|Polerhat
"""

_HOWRAH = """
গোলাবাড়ি|Golabari
মালিপাঁচঘড়া|Malipanchghora
লিলুয়া|Liluah|Lilua
বালি|Bally
বেলুড়|Belur
নিশ্চিন্দা|Nischinda
হাওড়া|Howrah
শিবপুর|Shibpur|Sibpur
আচার্য জগদীশচন্দ্র বসু বোটানিক্যাল গার্ডেন|Botanical Garden|Jagadish Chandra Bose Botanical Garden
ব্যাঁটরা|Bantra
চ্যাটার্জিহাট|Chatterjeehat
দাশনগর|Dasnagar
সাঁকরাইল|Sankrail
ডোমজুড়|Domjur
জগাছা|Jagacha
সাঁতরাগাছি|Santragachi
আমতা|Amta
বাগনান|Bagnan
বাউড়িয়া|Bauria
জগৎবল্লভপুর|Jagatballavpur
জয়পুর|Joypur
পাঁচলা|Panchla
পেঁড়ো|Pendo
রাজাপুর|Rajapur
শ্যামপুর|Shyampur
উদয়নারায়ণপুর|Udaynarayanpur
উলুবেড়িয়া|Uluberia
"""

_HOOGHLY = """
আরামবাগ|Arambagh
খানাকুল|Khanakul
গোঘাট|Goghat
পুরশুড়া|Pursurah
পোলবা|Polba
দাদপুর|Dadpur
ধনিয়াখালি|Dhaniakhali
গুড়াপ|Gurap
পান্ডুয়া|Pandua
মগরা|Magra
বলাগড়|Balagarh
চণ্ডীতলা|Chandital
জাঙ্গিপাড়া|Jangipara
সিঙ্গুর|Singur
হরিপাল|Haripal
তারকেশ্বর|Tarakeswar
চুঁচুড়া|Chinsurah|Chuchura/Chunchura
চন্দননগর|Chandannagar
ভদ্রেশ্বর|Bhadreswar
শ্রীরামপুর|Serampore|Srirampur
রিষড়া|Rishra
উত্তরপাড়া|Uttarpara
ডানকুনি|Dankuni
"""

_NORTH_24 = """
বারাসত|Barasat
মধ্যমগ্রাম|Madhyamgram
দত্তপুকুর|Duttapukur
দেগঙ্গা|Deganga
হাবড়া|Habra
অশোকনগর|Ashoknagar
আমডাঙা|Amdanga
গোবরডাঙা|Gobardanga
শাসন|Shasan
দক্ষিণেশ্বর|Dakshineswar
বীজপুর|Bijpur
হালিশহর|Halisahar
জেঠিয়া|Jetia
নৈহাটি|Naihati
ভাটপাড়া|Bhatpara
জগদ্দল|Jagaddal
নোয়াপাড়া|Noapara
ব্যারাকপুর|Barrackpore
টিটাগড়|Titagarh
খড়দহ|Khardah
রহড়া|Rahara
ঘোলা|Ghola
মোহনপুর|Mohanpur
নিউ ব্যারাকপুর|New Barrackpore
বেলঘরিয়া|Belgharia
কামারহাটি|Kamarhati
বরানগর|Baranagar
দমদম|Dum Dum
নাগেরবাজার|Nagerbazar
নিমতা|Nimta
শিবদাসপুর|Shibdaspur
বাসুদেবপুর|Basudebpur
বনগাঁ|Bongaon|Bangaon
বাগদা|Bagda
গাইঘাটা|Gaighata
গোপালনগর|Gopalnagar
পেট্রাপোল|Petrapole
বসিরহাট|Basirhat
বাদুড়িয়া|Baduria
মাটিয়া|Matia
স্বরূপনগর|Swarupnagar
হাড়োয়া|Haroa
মিনাখাঁ|Minakhan
হাসনাবাদ|Hasnabad
হিঙ্গলগঞ্জ|Hingalganj
সন্দেশখালি|Sandeshkhali
ন্যাজাট|Nazat
হেমনগর উপকূলীয়|Hemnagar Coastal
বিধাননগর পূর্ব|Bidhannagar East
বিধাননগর উত্তর|Bidhannagar North
বিধাননগর দক্ষিণ|Bidhannagar South
ইলেকট্রনিক্স কমপ্লেক্স|Electronics Complex
লেকটাউন|Lake Town
এয়ারপোর্ট|Airport
বাগুইআটি|Baguiati
নেতাজি সুভাষচন্দ্র বসু আন্তর্জাতিক বিমানবন্দর|Netaji Subhas Chandra Bose International Airport
ইকো পার্ক|Eco Park
নারায়ণপুর|Narayanpur
নিউটাউন|New Town
রাজারহাট|Rajarhat
টেকনো সিটি|Techno City
"""

_SOUTH_24 = """
বারুইপুর|Baruipur
জয়নগর|Joynagar
কুলতলি|Kultali
বকুলতলা|Bakultala
মৈপীঠ উপকূলীয়|Maipith Coastal
নরেন্দ্রপুর|Narendrapur
সোনারপুর|Sonarpur
ক্যানিং|Canning
বাসন্তী|Basanti
জীবনতলা|Jibantala
গোসাবা|Gosaba
সুন্দরবন উপকূলীয়|Sundarban Coastal
ঝড়খালি উপকূলীয়|Jharkhali Coastal
রবীন্দ্রনগর|Rabindranagar
মহেশতলা|Maheshtala
বজবজ|Budge Budge|Bajbaj
পুজালি|Pujali
কালীতলা আশুতি|Kalitala Ashuti
নোদাখালি|Nodakhali
বিষ্ণুপুর|Bishnupur
ডায়মন্ড হারবার|Diamond Harbour
ফলতা|Falta
উস্তি|Usthi
মগরাহাট|Magrahat
পারুলিয়া উপকূলীয়|Parulia Coastal
রামনগর|Ramnagar
কাকদ্বীপ|Kakdwip
মন্দিরবাজার|Mandirbazar
রায়দিঘি|Raidighi
ঢোলাহাট|Dholahat
মথুরাপুর|Mathurapur
কুলপি|Kulpi
নামখানা|Namkhana
সাগর|Sagar
পাথরপ্রতিমা|Patharpratima
ফ্রেজারগঞ্জ উপকূলীয়|Fraserganj Coastal
গোবর্ধনপুর উপকূলীয়|Gobardhanpur Coastal
গঙ্গাসাগর উপকূলীয়|Gangasagar Coastal
হারউড পয়েন্ট উপকূলীয়|Harwood Point Coastal
"""


def _rows(block: str) -> list[tuple[str, str, str]]:
    out = []
    for line in block.strip().splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 2 and parts[0] and parts[1]:
            out.append((parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
    return out


# district code -> [(Bengali, English, other Latin spellings "/"-joined)]
STATIONS_BY_DISTRICT: dict[str, list[tuple[str, str, str]]] = {
    "DIST_04": _rows(_KOLKATA),
    "DIST_05": _rows(_HOWRAH),
    "DIST_06": _rows(_HOOGHLY),
    "DIST_08": _rows(_NORTH_24),
    "DIST_09": _rows(_SOUTH_24) + _rows(_BHANGAR),
}

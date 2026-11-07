# Сервера Black Russia. Порт у всех 5125.
# Формат: "NAME последний_октет" (IP вида 80.66.82.X).
# Строка "# Название" начинает новую группу — по группам работают фильтры в боте.
# Новый сервер = просто добавь строку в нужную группу.
_RAW = """
# 🎨 Цветные
RED 46
GREEN 47
BLUE 197
YELLOW 198
ORANGE 210
PURPLE 211
LIME 208
PINK 209
CHERRY 236
BLACK 237
INDIGO 233
WHITE 234
MAGENTA 253
CRIMSON 254
GOLD 180
AZURE 181
PLATINUM 175
AQUA 176
GRAY 171
ICE 170
CHILLI 166
CHOCO 167

# 🏙 Города
MOSCOW 157
SPB 158
UFA 151
SOCHI 152
KAZAN 145
SAMARA 146
ASTANA 231
MAKHACHKALA 115
MAGADAN 249
CHITA 43
GROZNY 130
NORILSK 154
EKB 137
CHEREPOVETS 153
KRASNODAR 138
PODOLSK 104
ASTRAKHAN 42
YAKUTSK 53
VOLGOGRAD 120
OMSK 125
ROSTOV 140
CHELYABINSK 108
VLADIKAVKAZ 111
VLADIVOSTOK 187
PERM 95
STAVROPOL 67
SARATOV 131
ARZAMAS 134
VORONEZH 121
KEMEROVO 74
IRKUTSK 126
TOMSK 24
KURSK 83
NOVOSIB 135
KRASNOYARSK 100
KALININGRAD 107
TULA 92
CHEBOKSARY 101
ORENBURG 76
SURGUT 21
KHABAROVSK 94
BRYANSK 183
OREL 64
TYUMEN 75
PENZA 86
ANAPA 141
BARNAUL 56
RYAZAN 93
YAROSLAVL 65
KIROV 77
BELGOROD 114
ULYANOVSK 52
MURMANSK 85
KOSTROMA 38
TOLYATTI 72
VLADIMIR 36
IVANOVO 73
PSKOV 124
TAGANROG 26
SMOLENSK 68
LIPETSK 57
ARKHANGELSK 84
VOLOGDA 27
TVER 23
TAMBOV 50
KALUGA 35
BRATSK 51
IZHEVSK 20
NOVGOROD 34
"""

# Русские названия — нужны только для текстового поиска (напиши боту «москва»).
# Необязательно: сервер без алиаса просто ищется по латинскому имени.
_ALIASES_RAW = """
RED красный
GREEN зеленый
BLUE синий голубой
YELLOW желтый
ORANGE оранжевый
PURPLE фиолетовый
LIME лайм
PINK розовый
CHERRY вишня вишневый
BLACK черный
INDIGO индиго
WHITE белый
MAGENTA маджента
CRIMSON малиновый кримсон
GOLD золотой голд
AZURE лазурный
PLATINUM платина платиновый
AQUA аква
GRAY серый грей
ICE лед айс
CHILLI чили
CHOCO шоколад чоко
MOSCOW москва
SPB питер спб петербург
UFA уфа
SOCHI сочи
KAZAN казань
SAMARA самара
ASTANA астана
MAKHACHKALA махачкала
MAGADAN магадан
CHITA чита
GROZNY грозный
NORILSK норильск
EKB екб екатеринбург
CHEREPOVETS череповец
KRASNODAR краснодар
PODOLSK подольск
ASTRAKHAN астрахань
YAKUTSK якутск
VOLGOGRAD волгоград
OMSK омск
ROSTOV ростов
CHELYABINSK челябинск
VLADIKAVKAZ владикавказ
VLADIVOSTOK владивосток
PERM пермь
STAVROPOL ставрополь
SARATOV саратов
ARZAMAS арзамас
VORONEZH воронеж
KEMEROVO кемерово
IRKUTSK иркутск
TOMSK томск
KURSK курск
NOVOSIB новосибирск новосиб
KRASNOYARSK красноярск
KALININGRAD калининград
TULA тула
CHEBOKSARY чебоксары
ORENBURG оренбург
SURGUT сургут
KHABAROVSK хабаровск
BRYANSK брянск
OREL орел
TYUMEN тюмень
PENZA пенза
ANAPA анапа
BARNAUL барнаул
RYAZAN рязань
YAROSLAVL ярославль
KIROV киров
BELGOROD белгород
ULYANOVSK ульяновск
MURMANSK мурманск
KOSTROMA кострома
TOLYATTI тольятти
VLADIMIR владимир
IVANOVO иваново
PSKOV псков
TAGANROG таганрог
SMOLENSK смоленск
LIPETSK липецк
ARKHANGELSK архангельск
VOLOGDA вологда
TVER тверь
TAMBOV тамбов
KALUGA калуга
BRATSK братск
IZHEVSK ижевск
NOVGOROD новгород
"""

PORT = 5125


def _parse():
    servers, group_of, groups = [], [], []
    for line in _RAW.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            groups.append(line.lstrip("# ").strip())
            continue
        if not groups:
            groups.append("📋 Все")
        name, octet = line.split()
        servers.append((name, f"80.66.82.{octet}"))
        group_of.append(len(groups) - 1)
    aliases = {}
    for line in _ALIASES_RAW.strip().splitlines():
        name, *words = line.split()
        aliases[name] = words
    return servers, group_of, groups, aliases


SERVERS, GROUP_OF, GROUPS, ALIASES = _parse()
# SERVERS: [(имя, ip)]; GROUP_OF[i] — номер группы сервера i; GROUPS — названия групп.

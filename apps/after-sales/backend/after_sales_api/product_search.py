"""Product search semantics aligned with the mall catalogue search."""

import re
import unicodedata


PINYIN_RANGES = (
    (0xB0A1, 0xB0C4, "a"), (0xB0C5, 0xB2C2, "b"), (0xB2C3, 0xB4ED, "c"),
    (0xB4EE, 0xB6E9, "d"), (0xB6EA, 0xB7A1, "e"), (0xB7A2, 0xB8C0, "f"),
    (0xB8C1, 0xB9FD, "g"), (0xB9FE, 0xBBF6, "h"), (0xBBF7, 0xBFA5, "j"),
    (0xBFA6, 0xC0AB, "k"), (0xC0AC, 0xC2E7, "l"), (0xC2E8, 0xC4C2, "m"),
    (0xC4C3, 0xC5B5, "n"), (0xC5B6, 0xC5BD, "o"), (0xC5BE, 0xC6D9, "p"),
    (0xC6DA, 0xC8BA, "q"), (0xC8BB, 0xC8F5, "r"), (0xC8F6, 0xCBF9, "s"),
    (0xCBFA, 0xCDD9, "t"), (0xCDDA, 0xCEF3, "w"), (0xCEF4, 0xD1B8, "x"),
    (0xD1B9, 0xD4D0, "y"), (0xD4D1, 0xD7F9, "z"),
)
COMMON_SINGLE_CHARACTER_NOUNS = frozenset("桌椅凳柜床架台屏箱灯门窗板桶盆壶杯盘碗锅车")


def normalize(value):
    return unicodedata.normalize("NFKC", str(value or "")).casefold().strip()


def pinyin_initials(value):
    initials = []
    for char in str(value or ""):
        try:
            encoded = char.encode("gb2312")
        except UnicodeEncodeError:
            initials.append(char)
            continue
        if len(encoded) < 2:
            initials.append(char)
            continue
        code = (encoded[0] << 8) | encoded[1]
        initials.append(next((letter for low, high, letter in PINYIN_RANGES if low <= code <= high), char))
    return "".join(initials)


def _one_edit(left, right):
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) <= 1
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    short_index = long_index = differences = 0
    while short_index < len(shorter) and long_index < len(longer):
        if shorter[short_index] == longer[long_index]:
            short_index += 1
            long_index += 1
        else:
            differences += 1
            if differences > 1:
                return False
            long_index += 1
    return True


def matches_values(query, values):
    query = re.sub(r"\s+", "", normalize(query))
    if not query:
        return True
    variants = [query]
    if query.endswith("子"):
        stem = query[:-1]
        if stem and re.fullmatch(r"[\u3400-\u4dbf\u4e00-\u9fff]+", stem) and (
            len(stem) > 1 or stem in COMMON_SINGLE_CHARACTER_NOUNS
        ):
            variants.append(stem)
    fields = [value for value in values if value is not None and value != ""]
    candidates = [re.sub(r"\s+", "", normalize(value)) for value in fields]
    candidates += [re.sub(r"\s+", "", normalize(pinyin_initials(value))) for value in fields]
    if any(variant in "".join(candidates) for variant in variants):
        return True
    for variant in variants:
        if len(variant) < 4:
            continue
        deletions = [variant[:index] + variant[index + 1:] for index in range(len(variant))]
        if any(any(part in candidate for part in deletions) or (
            abs(len(variant) - len(candidate)) <= 1 and _one_edit(variant, candidate)
        ) for candidate in candidates if candidate):
            return True
    return False


def matches_product(query, row):
    return matches_values(query, [
        row.get(key) for key in (
            "abbr", "label", "product_model", "product_brand", "kingdeeCode",
            "product_domain", "category_a", "category_b",
        )
    ])


def filter_queryset_search(queryset, query, fields):
    if not normalize(query):
        return queryset
    matched_ids = []
    for product_id, *values in queryset.order_by().values_list("pk", *fields).iterator(chunk_size=500):
        if matches_values(query, values):
            matched_ids.append(product_id)
    return queryset.filter(pk__in=matched_ids)

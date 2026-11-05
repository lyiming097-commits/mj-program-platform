import re
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from competitive_vue_api.domain import (
    competitor_parameter_text,
    competitor_snapshot,
    next_version_number,
    parameter_candidate_text,
    split_competitor_parameter_text,
    sync_competitor_parameters,
)
from competitive_vue_api.models import Competitor, CompetitorVersion
from competitive_vue_api.releases import sync_current_release_from_competitor


LEGACY_ITEM_PREFIX_RE = re.compile(
    r"^(?:\s*\d{1,3}\s*(?:(?:[.．](?!\d)|[、:：)）]|\-(?!\d))\s*|(?=[\u4e00-\u9fff])\s*)|[\uFF08(\u3010\[]\s*\d{1,3}\s*[\uFF09)\u3011\]]\s*)"
)
LEGACY_NUMBERED_START_RE = re.compile(
    r"(?:^|[\r\n;；\s])(\d{1,3}\s*(?=[\u4e00-\u9fff]))|(?<!\d)\d{1,3}\s*(?:[.．](?!\d)|[、:：)）]|\-(?!\d))\s*|(?<!\d)[\uFF08(\u3010\[]\s*\d{1,3}\s*[\uFF09)\u3011\]]\s*"
)


def _legacy_clean(value) -> str:
    return LEGACY_ITEM_PREFIX_RE.sub("", str(value or "").strip()).strip().rstrip(";；").strip()


def _legacy_normalize(value) -> str:
    if isinstance(value, list):
        return " / ".join(
            item
            for item in (parameter_candidate_text(candidate) for candidate in value)
            if item
        )
    return str(value or "").strip()


def _legacy_numbered_items(text: str) -> list[str]:
    starts = []
    for match in LEGACY_NUMBERED_START_RE.finditer(text):
        number_offset = match.group(0).find(match.group(1)) if match.group(1) else 0
        start = match.start() + number_offset
        if not starts or starts[-1] != start:
            starts.append(start)
    if not starts:
        return [text.strip()]
    prefix = text[: starts[0]].strip()
    if prefix and not re.fullmatch(r"[;；]+", prefix) and not re.search(r"[：:]$", prefix):
        return [text.strip()]
    return [
        _legacy_clean(text[start : starts[index + 1] if index + 1 < len(starts) else len(text)])
        for index, start in enumerate(starts)
        if text[start : starts[index + 1] if index + 1 < len(starts) else len(text)].strip()
    ]


def legacy_split_competitor_parameter_text(value) -> list[str]:
    text = _legacy_normalize(value)
    if re.search(r"[/／]", text):
        segments = re.split(r"[/／\r\n]+", text)
    else:
        numbered = _legacy_numbered_items(text)
        segments = numbered if len(numbered) > 1 or numbered[0] != text else re.split(r"\r?\n+", text)
    result = []
    seen = set()
    for segment in segments:
        item = _legacy_clean(segment)
        key = item.casefold()
        if item and key not in seen:
            result.append(item)
            seen.add(key)
    return result


class Command(BaseCommand):
    help = "Repair formal parameters only when they exactly match the legacy parser output."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply exact-match repairs. Without this flag the command is read-only.",
        )

    def handle(self, *args, **options):
        apply_changes = bool(options["apply"])
        repaired_count = 0
        skipped_count = 0
        queryset = Competitor.objects.filter(deleted_at__isnull=True).prefetch_related(
            "parameters",
            "submissions",
            "versions",
        )
        for competitor in queryset:
            current = [competitor_parameter_text(item) for item in competitor.parameters.all()]
            exact_repairs = {}
            for submission in competitor.submissions.all():
                if submission.deleted_at is not None:
                    continue
                raw = submission.competitor_parameters
                if legacy_split_competitor_parameter_text(raw) != current:
                    continue
                repaired = split_competitor_parameter_text(raw)
                if repaired and repaired != current:
                    exact_repairs.setdefault(tuple(repaired), submission)
            if len(exact_repairs) != 1:
                if exact_repairs:
                    skipped_count += 1
                continue

            repaired_items, source_submission = next(iter(exact_repairs.items()))
            self.stdout.write(
                f"{competitor.id}: {len(current)} -> {len(repaired_items)} parameters"
            )
            repaired_count += 1
            if not apply_changes:
                continue
            with transaction.atomic():
                locked = Competitor.objects.select_for_update().prefetch_related(
                    "parameters", "versions"
                ).get(id=competitor.id)
                locked_current = [
                    competitor_parameter_text(item) for item in locked.parameters.all()
                ]
                if locked_current != current:
                    skipped_count += 1
                    repaired_count -= 1
                    self.stderr.write(f"{competitor.id}: changed during repair, skipped")
                    continue
                sync_competitor_parameters(locked, list(repaired_items))
                sync_current_release_from_competitor(locked)
                CompetitorVersion.objects.create(
                    competitor=locked,
                    version=f"V{next_version_number(locked)}",
                    changed_on=date.today(),
                    note="修复旧版参数自动分割造成的错误断行。",
                    action="系统修复",
                    changed_by="系统",
                    source_submission=source_submission,
                    snapshot=competitor_snapshot(locked),
                )

        mode = "applied" if apply_changes else "found"
        self.stdout.write(
            self.style.SUCCESS(
                f"Parameter repair {mode}: {repaired_count}; skipped: {skipped_count}."
            )
        )

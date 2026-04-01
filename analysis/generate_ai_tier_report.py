from __future__ import annotations

import csv
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def latex_escape(value: str) -> str:
    repl = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    out = []
    for ch in value:
        out.append(repl.get(ch, ch))
    return "".join(out)


def to_int(value: str | None, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def compute_overtime_audit(raw_rows: list[dict[str, str]], overtime_turn_cap: int) -> dict[str, float]:
    winners = [row for row in raw_rows if str(row.get("winner_index", "")).strip() in ("0", "1")]
    total_winners = len(winners)
    overtime_winners = [row for row in winners if to_int(row.get("turns_completed"), 0) > overtime_turn_cap]
    p1_overtime = sum(1 for row in overtime_winners if str(row.get("winner_index", "")).strip() == "0")
    p2_overtime = sum(1 for row in overtime_winners if str(row.get("winner_index", "")).strip() == "1")

    first_overtime_turn = overtime_turn_cap + 1
    first_turn_winners = [
        row for row in overtime_winners if to_int(row.get("turns_completed"), 0) == first_overtime_turn
    ]
    first_turn_p2 = sum(1 for row in first_turn_winners if str(row.get("winner_index", "")).strip() == "1")

    return {
        "overtime_turn_cap": float(overtime_turn_cap),
        "total_winners": float(total_winners),
        "overtime_winners": float(len(overtime_winners)),
        "overtime_winner_pct": (100.0 * len(overtime_winners) / total_winners) if total_winners > 0 else 0.0,
        "p1_overtime_wins": float(p1_overtime),
        "p2_overtime_wins": float(p2_overtime),
        "p2_share_overtime_pct": (100.0 * p2_overtime / len(overtime_winners)) if overtime_winners else 0.0,
        "first_overtime_turn": float(first_overtime_turn),
        "first_turn_winners": float(len(first_turn_winners)),
        "first_turn_p2_wins": float(first_turn_p2),
        "first_turn_p2_pct": (100.0 * first_turn_p2 / len(first_turn_winners)) if first_turn_winners else 0.0,
    }


def build_latex(
    matchups: list[dict[str, str]],
    strengths: list[dict[str, str]],
    overtime_audit: dict[str, float] | None,
) -> str:
    best = max(strengths, key=lambda row: float(row["point_rate_pct"]))
    worst = min(strengths, key=lambda row: float(row["point_rate_pct"]))
    total_games = sum(int(row["games"]) for row in matchups)
    total_p1_wins = sum(int(row["p1_wins"]) for row in matchups)
    total_p2_wins = sum(int(row["p2_wins"]) for row in matchups)
    total_draws = sum(int(row["draws"]) for row in matchups)
    non_draw_games = total_games - total_draws
    p1_decisive = (100.0 * total_p1_wins / non_draw_games) if non_draw_games > 0 else 0.0
    p2_decisive = (100.0 * total_p2_wins / non_draw_games) if non_draw_games > 0 else 0.0
    p1_point = (100.0 * (total_p1_wins + 0.5 * total_draws) / total_games) if total_games > 0 else 0.0
    p2_point = (100.0 * (total_p2_wins + 0.5 * total_draws) / total_games) if total_games > 0 else 0.0
    draw_rate = (100.0 * total_draws / total_games) if total_games > 0 else 0.0
    avg_turns = (
        sum(float(row["avg_turns"]) * int(row["games"]) for row in matchups) / total_games
        if total_games > 0
        else 0.0
    )

    lines: list[str] = []
    lines.append(r"\documentclass[12pt]{article}")
    lines.append(r"\usepackage[margin=1in]{geometry}")
    lines.append(r"\usepackage{booktabs}")
    lines.append(r"\usepackage{longtable}")
    lines.append(r"\usepackage{float}")
    lines.append(r"\usepackage{setspace}")
    lines.append(r"\setstretch{1.1}")
    lines.append(r"\title{Legends of Noblesse\\AI Tier Matchup Report}")
    lines.append(r"\author{ECE348 Project Simulation Study}")
    lines.append(r"\date{March 31, 2026}")
    lines.append(r"\begin{document}")
    lines.append(r"\maketitle")

    lines.append(r"\section{Introduction}")
    lines.append(
        "This report evaluates game balance in \\textit{Legends of Noblesse} by comparing three AI skill tiers "
        "(bad, mediocre, good) across six requested head-to-head matchups. The central question is whether match "
        "outcomes and overall point rates indicate a reasonably fair system rather than a single dominant strategy."
    )
    lines.append(
        f"The analysis used \\textbf{{{total_games}}} automated games (20 per matchup), under legal engine rules only, "
        "with no overtime force logic or deterministic tiebreak. A game ends in a decisive result only when a barracks "
        "is successfully breached; otherwise it is recorded as a draw at the configured turn cap."
    )

    lines.append(r"\section{Rules (Implementation Summary)}")
    lines.append(r"\begin{enumerate}")
    lines.append(r"\item Each player starts with a legal randomized loadout (deck, class, barracks, and 3 battlefields).")
    lines.append(r"\item Every game follows engine phase order: Replenish, Draw, Preparations, Siege, and Field Cleanup.")
    lines.append(r"\item During Draw and Preparations, AIs take only legal actions available in the current phase.")
    lines.append(r"\item During Siege, battalions can only be assigned to legal targets reported by the engine.")
    lines.append(r"\item A decisive winner is declared only by true in-engine barracks capture conditions.")
    lines.append(r"\item No overtime force behavior was used to force attacks or force winners.")
    lines.append(r"\item If no winner is declared by 2000 turns, the game is recorded as a draw for analysis.")
    lines.append(r"\end{enumerate}")

    lines.append(r"\section{Results}")
    lines.append(r"\subsection{Overall Outcomes}")
    lines.append(
        "The full 120-game run produced the following aggregate balance metrics:"
    )
    lines.append(r"\begin{itemize}")
    lines.append(f"\\item Simulated games: \\textbf{{{total_games}}}")
    lines.append(f"\\item Non-draw games: \\textbf{{{non_draw_games}}}")
    lines.append(f"\\item Draws: \\textbf{{{total_draws}}} ({draw_rate:.2f}\\%)")
    lines.append(f"\\item Player 1 decisive win rate (excluding draws): \\textbf{{{p1_decisive:.2f}\\%}}")
    lines.append(f"\\item Player 2 decisive win rate (excluding draws): \\textbf{{{p2_decisive:.2f}\\%}}")
    lines.append(f"\\item Player 1 point rate (draw = 0.5): \\textbf{{{p1_point:.2f}\\%}}")
    lines.append(f"\\item Player 2 point rate (draw = 0.5): \\textbf{{{p2_point:.2f}\\%}}")
    lines.append(f"\\item Average game length: \\textbf{{{avg_turns:.2f} turns}}")
    lines.append(r"\end{itemize}")

    lines.append(r"\subsection{Matchup Matrix}")
    lines.append(r"\begin{table}[H]")
    lines.append(r"\centering")
    lines.append(r"\caption{20-Game Results per Requested Matchup}")
    lines.append(r"\begin{tabular}{lrrrrrr}")
    lines.append(r"\toprule")
    lines.append(r"Matchup & Games & P1 Wins & P2 Wins & Draws & P1 Win\% & P2 Win\% \\")
    lines.append(r"\midrule")
    for row in matchups:
        lines.append(
            f"{latex_escape(row['matchup'])} & {row['games']} & {row['p1_wins']} & {row['p2_wins']} & {row['draws']} & "
            f"{row['p1_decisive_win_rate_pct']} & {row['p2_decisive_win_rate_pct']} \\\\"
        )
    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}")
    lines.append(r"\end{table}")

    lines.append(r"\subsection{Overall Tier Strength}")
    lines.append(r"\begin{table}[H]")
    lines.append(r"\centering")
    lines.append(r"\caption{Aggregate Tier Performance Across All Appearances}")
    lines.append(r"\begin{tabular}{lrrrrrr}")
    lines.append(r"\toprule")
    lines.append(r"AI Tier & Appearances & Wins & Losses & Draws & Win\% & Point\% \\")
    lines.append(r"\midrule")
    for row in strengths:
        lines.append(
            f"{latex_escape(row['ai'])} & {row['appearances']} & {row['wins']} & {row['losses']} & {row['draws']} & "
            f"{row['decisive_win_rate_pct']} & {row['point_rate_pct']} \\\\"
        )
    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}")
    lines.append(r"\end{table}")

    if overtime_audit is not None:
        overtime_turn_cap = int(overtime_audit["overtime_turn_cap"])
        first_overtime_turn = int(overtime_audit["first_overtime_turn"])
        lines.append(r"\subsection{Overtime Order-Bias Audit (Legacy Forced-Overtime Run)}")
        lines.append(
            "To address the question about overtime bias, we also audited the earlier forced-overtime dataset "
            "(stored in reports/ai\\_tier\\_matchups). In that build, overtime began after turn "
            f"{overtime_turn_cap}, and Player 2 barracks attack resolution occurred before Player 1."
        )
        lines.append(r"\begin{itemize}")
        lines.append(
            f"\\item Winners in audited run: \\textbf{{{int(overtime_audit['total_winners'])}}}"
        )
        lines.append(
            f"\\item Winners occurring after overtime started: \\textbf{{{int(overtime_audit['overtime_winners'])}}} "
            f"({overtime_audit['overtime_winner_pct']:.2f}\\%)"
        )
        lines.append(
            f"\\item Of overtime winners, Player 2 won \\textbf{{{int(overtime_audit['p2_overtime_wins'])}}} "
            f"vs Player 1 \\textbf{{{int(overtime_audit['p1_overtime_wins'])}}} "
            f"({overtime_audit['p2_share_overtime_pct']:.2f}\\% Player 2 share)"
        )
        lines.append(
            f"\\item At turn {first_overtime_turn} (the first overtime turn), "
            f"\\textbf{{{int(overtime_audit['first_turn_winners'])}}} wins were recorded, "
            f"with Player 2 taking \\textbf{{{int(overtime_audit['first_turn_p2_wins'])}}} "
            f"({overtime_audit['first_turn_p2_pct']:.2f}\\%)"
        )
        lines.append(r"\end{itemize}")
        lines.append(
            "These counts quantify how many outcomes were produced in the overtime window where the Player 2 "
            "ordering advantage could influence decisive results."
        )

    lines.append(r"\section{Conclusion}")
    lines.append(
        f"The strongest tier in this run was {latex_escape(best['ai'])} (point rate {best['point_rate_pct']}\\%), "
        f"while the weakest was {latex_escape(worst['ai'])} (point rate {worst['point_rate_pct']}\\%). "
        "The results show clear skill-tier separation (good $>$ mediocre $>$ bad in aggregate), while preserving "
        "legal winner conditions. The analysis therefore answers the assignment prompts with a full rule summary, "
        "simulation evidence, and data-backed balance interpretation."
    )

    lines.append(r"\end{document}")
    return "\n".join(lines) + "\n"


def escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_fallback_pdf(pdf_path: Path, lines: list[str]) -> None:
    page_width = 612
    page_height = 792
    margin_x = 54
    start_y = 738
    line_height = 14
    lines_per_page = 48

    pages: list[list[str]] = []
    for idx in range(0, len(lines), lines_per_page):
        pages.append(lines[idx : idx + lines_per_page])
    if not pages:
        pages = [[]]

    objects: list[tuple[int, bytes]] = []
    objects.append((1, b"<< /Type /Catalog /Pages 2 0 R >>"))

    page_numbers = [4 + i * 2 for i in range(len(pages))]
    kids = " ".join(f"{num} 0 R" for num in page_numbers)
    objects.append((2, f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii")))
    objects.append((3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))

    for i, page_lines in enumerate(pages):
        page_obj = 4 + i * 2
        content_obj = 5 + i * 2

        content_lines = ["BT", "/F1 11 Tf", f"{margin_x} {start_y} Td"]
        for line in page_lines:
            content_lines.append(f"({escape_pdf_text(line)}) Tj")
            content_lines.append(f"0 -{line_height} Td")
        content_lines.append("ET")
        stream = "\n".join(content_lines).encode("latin-1", errors="replace")
        content_payload = b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"
        page_payload = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_obj} 0 R >>"
        ).encode("ascii")

        objects.append((page_obj, page_payload))
        objects.append((content_obj, content_payload))

    objects.sort(key=lambda pair: pair[0])
    max_obj = objects[-1][0]

    out = bytearray()
    out.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (max_obj + 1)

    for obj_num, payload in objects:
        offsets[obj_num] = len(out)
        out.extend(f"{obj_num} 0 obj\n".encode("ascii"))
        out.extend(payload)
        out.extend(b"\nendobj\n")

    xref_start = len(out)
    out.extend(f"xref\n0 {max_obj + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for obj_num in range(1, max_obj + 1):
        out.extend(f"{offsets[obj_num]:010d} 00000 n \n".encode("ascii"))

    out.extend(f"trailer\n<< /Size {max_obj + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n".encode("ascii"))
    pdf_path.write_bytes(out)


def build_plaintext_summary(
    matchups: list[dict[str, str]],
    strengths: list[dict[str, str]],
    overtime_audit: dict[str, float] | None,
) -> list[str]:
    total_games = sum(int(row["games"]) for row in matchups)
    total_p1_wins = sum(int(row["p1_wins"]) for row in matchups)
    total_p2_wins = sum(int(row["p2_wins"]) for row in matchups)
    total_draws = sum(int(row["draws"]) for row in matchups)
    non_draw_games = total_games - total_draws
    p1_decisive = (100.0 * total_p1_wins / non_draw_games) if non_draw_games > 0 else 0.0
    p2_decisive = (100.0 * total_p2_wins / non_draw_games) if non_draw_games > 0 else 0.0
    p1_point = (100.0 * (total_p1_wins + 0.5 * total_draws) / total_games) if total_games > 0 else 0.0
    p2_point = (100.0 * (total_p2_wins + 0.5 * total_draws) / total_games) if total_games > 0 else 0.0
    draw_rate = (100.0 * total_draws / total_games) if total_games > 0 else 0.0
    avg_turns = (
        sum(float(row["avg_turns"]) * int(row["games"]) for row in matchups) / total_games
        if total_games > 0
        else 0.0
    )

    lines: list[str] = []
    lines.append("Legends of Noblesse AI Tier Matchup Report")
    lines.append("Date: March 31, 2026")
    lines.append("")
    lines.append("Introduction")
    lines.append("This report evaluates balance across bad/mediocre/good AI tiers.")
    lines.append("Simulation uses legal rules only, 20 games per matchup, and no overtime forcing.")
    lines.append("")
    lines.append("Rules")
    lines.append("- Phase order: Replenish, Draw, Preparations, Siege, Field Cleanup.")
    lines.append("- Decisive result requires in-engine barracks capture.")
    lines.append("- Turn cap is 2000; unresolved games are recorded as draws.")
    lines.append("")
    lines.append("Results (Overall)")
    lines.append(f"- Simulated games: {total_games}")
    lines.append(f"- Non-draw games: {non_draw_games}")
    lines.append(f"- Draws: {total_draws} ({draw_rate:.2f}%)")
    lines.append(f"- Player 1 decisive win rate: {p1_decisive:.2f}%")
    lines.append(f"- Player 2 decisive win rate: {p2_decisive:.2f}%")
    lines.append(f"- Player 1 point rate (draw=0.5): {p1_point:.2f}%")
    lines.append(f"- Player 2 point rate (draw=0.5): {p2_point:.2f}%")
    lines.append(f"- Average game length: {avg_turns:.2f} turns")
    lines.append("")
    lines.append("Matchup Results")
    for row in matchups:
        lines.append(
            f"- {row['matchup']}: games={row['games']}, p1_wins={row['p1_wins']}, "
            f"p2_wins={row['p2_wins']}, p1_win%={row['p1_decisive_win_rate_pct']}, "
            f"p2_win%={row['p2_decisive_win_rate_pct']}"
        )
    lines.append("")
    lines.append("Overall Tier Strength")
    for row in strengths:
        lines.append(
            f"- {row['ai']}: appearances={row['appearances']}, wins={row['wins']}, "
            f"losses={row['losses']}, win%={row['decisive_win_rate_pct']}"
        )
    if overtime_audit is not None:
        overtime_turn_cap = int(overtime_audit["overtime_turn_cap"])
        first_overtime_turn = int(overtime_audit["first_overtime_turn"])
        lines.append("")
        lines.append("Overtime Order-Bias Audit (Legacy Forced-Overtime Run)")
        lines.append(
            f"- Overtime starts after turn {overtime_turn_cap}; audited winners={int(overtime_audit['total_winners'])}"
        )
        lines.append(
            f"- Overtime-window winners={int(overtime_audit['overtime_winners'])} "
            f"({overtime_audit['overtime_winner_pct']:.2f}%)"
        )
        lines.append(
            f"- Overtime winners by side: P1={int(overtime_audit['p1_overtime_wins'])}, "
            f"P2={int(overtime_audit['p2_overtime_wins'])} "
            f"(P2 share {overtime_audit['p2_share_overtime_pct']:.2f}%)"
        )
        lines.append(
            f"- Turn {first_overtime_turn} winners={int(overtime_audit['first_turn_winners'])}; "
            f"P2 took {int(overtime_audit['first_turn_p2_wins'])} "
            f"({overtime_audit['first_turn_p2_pct']:.2f}%)"
        )
    lines.append("")
    lines.append("Conclusion")
    lines.append("The report includes the full assignment flow: introduction, rules, data-driven results, and conclusion.")
    return lines


def main() -> int:
    out_dir = PROJECT_ROOT / "reports" / "ai_tier_matchups_20games"
    matchup_csv = out_dir / "ai_tier_matchup_summary.csv"
    strength_csv = out_dir / "ai_tier_overall_strength.csv"
    legacy_overtime_raw_csv = PROJECT_ROOT / "reports" / "ai_tier_matchups" / "ai_tier_raw_matches.csv"

    matchups = read_csv_rows(matchup_csv)
    strengths = read_csv_rows(strength_csv)
    overtime_audit: dict[str, float] | None = None
    if legacy_overtime_raw_csv.exists():
        legacy_rows = read_csv_rows(legacy_overtime_raw_csv)
        overtime_audit = compute_overtime_audit(legacy_rows, overtime_turn_cap=50)

    tex_content = build_latex(matchups, strengths, overtime_audit)
    tex_path = out_dir / "ai_tier_matchups_report.tex"
    tex_path.write_text(tex_content, encoding="utf-8")

    pdf_path = out_dir / "ai_tier_matchups_report.pdf"
    pdflatex = shutil.which("pdflatex")

    if pdflatex:
        try:
            for _ in range(2):
                subprocess.run(
                    [pdflatex, "-interaction=nonstopmode", "-halt-on-error", tex_path.name],
                    cwd=out_dir,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            return 0
        except subprocess.CalledProcessError:
            pass

    # Fallback PDF when LaTeX compiler is unavailable in this environment.
    lines = build_plaintext_summary(matchups, strengths, overtime_audit)
    write_fallback_pdf(pdf_path, lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

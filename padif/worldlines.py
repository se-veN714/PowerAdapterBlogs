"""Presentation-only worldline geometry; versions and ancestry remain unchanged."""


def build_worldlines(main, rows, cards, selected_versions):
    lanes = {main.pk: 340}
    ordered_cards = sorted(cards, key=lambda card: not card["selected"])
    for card, x in zip(ordered_cards, (70, 210, 570)):
        lanes[card["branch"].pk] = x

    versions = {row["version"].pk: row["version"] for row in rows}
    for card in cards:
        branch = card["branch"]
        if card["head"]:
            versions[card["head"].pk] = card["head"]
        if branch.forked_from_id:
            versions[branch.forked_from_id] = branch.forked_from
    for version in selected_versions:
        versions[version.pk] = version

    ordered_versions = sorted(versions.values(), key=lambda version: version.pk, reverse=True)
    step = max(28, min(48, 420 / max(len(ordered_versions) - 1, 1)))
    y = {version.pk: round(110 + index * step, 2) for index, version in enumerate(ordered_versions)}
    height = round(max(350, (max(y.values()) if y else 200) + 72))
    paths, nodes, heads, origins = [], [], [], []

    main_versions = [row["version"] for row in rows]
    # Include actual fork sources on main, even when only an older anchor is shown.
    main_versions = list({version.pk: version for version in main_versions + list(versions.values())
                          if version.branch_id == main.pk}.values())
    if main_versions:
        main_head = max(main_versions, key=lambda version: version.pk)
        oldest = min(main_versions, key=lambda version: version.pk)
        paths.append({"d": f"M 340 {y[oldest.pk]} V {y[main_head.pk]}", "kind": "main"})
        heads.append({"branch": main, "version": main_head, "left": 50, "top": y[main_head.pk] - 58,
                      "selected": not any(card["selected"] for card in cards), "main": True})

    for card in ordered_cards:
        branch = card["branch"]
        head = card["head"]
        source = branch.forked_from
        x = lanes[branch.pk]
        if not source:
            continue
        source_x = lanes.get(source.branch_id, x)
        source_y = y[source.pk]
        head_y = y[head.pk] if head else source_y - 42
        # An omitted parent branch is labelled explicitly; never invent a direct main fork.
        if source.branch_id not in lanes:
            origins.append({"left": x / 6.8, "top": source_y + 10,
                            "label": f"源于 {source.branch.name} · v{source.semantic_version}"})
        corner_y = source_y - min(20, max(10, (source_y - head_y) / 2))
        paths.append({"d": f"M {source_x} {source_y} H {x - (12 if x > source_x else -12)} L {x} {corner_y} V {head_y}",
                      "kind": "selected" if card["selected"] else "branch"})
        heads.append({"branch": branch, "version": head, "left": x / 6.8, "top": head_y - 58,
                      "selected": card["selected"], "main": False})
        card["graph_head_y"] = head_y

    for version in ordered_versions:
        if version.branch_id not in lanes:
            continue
        is_main = version.branch_id == main.pk
        is_selected = any(card["selected"] and card["branch"].pk == version.branch_id for card in cards)
        # Nonselected branch histories stay at their head summary, except real fork junctions.
        if not is_main and not is_selected and not any(card["head"] and card["head"].pk == version.pk for card in cards) and not any(card["branch"].forked_from_id == version.pk for card in cards):
            continue
        nodes.append({"version": version, "left": lanes[version.branch_id] / 6.8,
                      "top": y[version.pk], "main": is_main, "selected": is_selected,
                      "head": any(item["version"] and item["version"].pk == version.pk for item in heads)})
    paths.sort(key=lambda path: {"main": 0, "branch": 1, "selected": 2}[path["kind"]])
    return {"height": height, "paths": paths, "nodes": nodes, "heads": heads, "origins": origins}

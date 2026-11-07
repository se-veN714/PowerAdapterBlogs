"""Presentation-only worldline geometry; versions and ancestry remain unchanged."""


def build_worldlines(main, rows, cards, recent_versions):
    lanes = {main.pk: 340}
    # Selection changes emphasis, not lane placement, so switching does not shuffle the tree.
    ordered_cards = sorted(cards, key=lambda card: (card["branch"].last_activity, card["branch"].pk), reverse=True)
    for card, x in zip(ordered_cards, (110, 230, 550)):
        lanes[card["branch"].pk] = x

    versions = {row["version"].pk: row["version"] for row in rows}
    for card in cards:
        branch = card["branch"]
        if card["head"]:
            versions[card["head"].pk] = card["head"]
        if branch.forked_from_id:
            versions[branch.forked_from_id] = branch.forked_from
    for version in recent_versions:
        versions[version.pk] = version

    ordered_versions = sorted(versions.values(), key=lambda version: version.pk, reverse=True)
    step = max(20, min(34, 300 / max(len(ordered_versions) - 1, 1)))
    y = {version.pk: round(94 + index * step, 2) for index, version in enumerate(ordered_versions)}
    height = round(max(260, (max(y.values()) if y else 180) + 42))
    paths, nodes, heads, origins = [], [], [], []

    main_versions = [row["version"] for row in rows]
    # Include actual fork sources on main, even when only an older anchor is shown.
    main_versions = list({version.pk: version for version in main_versions + list(versions.values())
                          if version.branch_id == main.pk}.values())
    if main_versions:
        main_head = max(main_versions, key=lambda version: version.pk)
        oldest = min(main_versions, key=lambda version: version.pk)
        paths.append({"d": f"M 340 {y[oldest.pk]} V {y[main_head.pk]}", "kind": "main"})
        heads.append({"branch": main, "version": main_head, "left": 50, "top": y[main_head.pk] - 52,
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
        heads.append({"branch": branch, "version": head, "left": x / 6.8, "top": head_y - 52,
                      "selected": card["selected"], "main": False})
        card["graph_head_y"] = head_y

    for version in ordered_versions:
        if version.branch_id not in lanes:
            continue
        is_main = version.branch_id == main.pk
        is_selected = any(card["selected"] and card["branch"].pk == version.branch_id for card in cards)
        # Every visible lane gets its actual recent iterations, while descriptions
        # remain expanded only in the selected branch inspector.
        nodes.append({"version": version, "left": lanes[version.branch_id] / 6.8,
                      "top": y[version.pk], "main": is_main, "selected": is_selected,
                      "head": any(item["version"] and item["version"].pk == version.pk for item in heads)})
    paths.sort(key=lambda path: {"main": 0, "branch": 1, "selected": 2}[path["kind"]])
    return {"height": height, "paths": paths, "nodes": nodes, "heads": heads, "origins": origins}

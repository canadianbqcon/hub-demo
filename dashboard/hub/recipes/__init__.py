# recipes — Hub module: the markdown recipe library, made cookable.
#
# Reads recipes/*.md straight from the vault; there is no recipes.db and no write path
# back to the notes. The module's ONE write surface is the canonical grocery list, which
# lives in checklists.db and is shared with /checklists rather than copied here.

"""Recipes page: it reads <vault>/recipes/*.md, so this module only writes files.

Fictional home recipes, no photos (the cards show the empty tinted slot).
"""
DB = None
EXPECT = {}

# slug, title, categories, servings, prep, cook, difficulty, source, ingredients, directions, notes
R = [
    ("weeknight-chicken-tikka", "Weeknight Chicken Tikka Masala", ["Dinner", "Indian", "Chicken"], "4", "20 min", "35 min", "Easy", "Family recipe",
     ["1.5 lb chicken thighs, cubed", "1 cup plain yogurt", "2 tbsp garam masala", "1 tbsp grated ginger", "4 cloves garlic, minced", "1 can (14 oz) crushed tomatoes", "1/2 cup heavy cream", "2 tbsp butter", "1 onion, diced"],
     ["Marinate the chicken in the yogurt, half the garam masala, ginger and garlic for at least 30 minutes.", "Broil or sear the chicken until charred at the edges, about 8 minutes.", "Melt the butter, soften the onion, add the rest of the spices, then the tomatoes. Simmer 15 minutes.", "Stir in the cream and chicken and simmer 5 minutes. Serve over rice."],
     "Better the next day. Add a squeeze of lemon at the end."),
    ("sunday-bolognese", "Sunday Bolognese", ["Dinner", "Italian", "Pasta"], "6", "25 min", "3 hr", "Medium", "Family recipe",
     ["1 lb ground beef", "1/2 lb ground pork", "1 onion, finely diced", "2 carrots, finely diced", "2 celery stalks, finely diced", "3 tbsp tomato paste", "1 cup whole milk", "1 cup dry white wine", "1 can (28 oz) crushed tomatoes", "1 lb tagliatelle"],
     ["Brown the meats in batches and set aside.", "Cook the diced vegetables in the same pot until soft, 10 minutes. Add tomato paste and cook 2 minutes.", "Add the wine, then the milk, reducing each by half.", "Return the meat, add the tomatoes and simmer on low for 2.5 hours, stirring now and then.", "Toss with pasta and a ladle of pasta water."],
     "Freezes well in 2-cup portions."),
    ("crispy-smashed-potatoes", "Crispy Smashed Potatoes", ["Side", "Vegetarian"], "4", "10 min", "45 min", "Easy", "Notebook",
     ["1.5 lb baby potatoes", "3 tbsp olive oil", "1 tsp flaky salt", "2 tbsp chopped chives", "1 lemon"],
     ["Boil the potatoes in salted water until a knife slides in, about 20 minutes. Drain and let steam dry.", "Smash each with the bottom of a glass on an oiled sheet pan.", "Drizzle with oil and salt. Roast at 450F for 25 minutes, flipping once.", "Finish with chives and lemon zest."],
     "Dry potatoes are the whole trick."),
    ("miso-glazed-salmon", "Miso-Glazed Salmon", ["Dinner", "Japanese", "Fish"], "2", "10 min", "12 min", "Easy", "Friend recipe",
     ["2 salmon fillets", "2 tbsp white miso", "1 tbsp mirin", "1 tbsp soy sauce", "1 tsp rice vinegar", "1 tsp sesame seeds"],
     ["Whisk the miso, mirin, soy sauce and vinegar.", "Brush over the salmon and rest 15 minutes.", "Broil 8 to 10 minutes until the top caramelizes. Sprinkle with sesame."],
     "Watch it closely; the glaze burns fast."),
    ("lentil-soup", "Red Lentil Soup With Lemon", ["Soup", "Vegetarian", "Dinner"], "4", "10 min", "30 min", "Easy", "Notebook",
     ["1 cup red lentils", "1 onion, diced", "2 carrots, diced", "3 cloves garlic", "1 tsp cumin", "4 cups vegetable broth", "1 lemon, juiced", "2 tbsp olive oil"],
     ["Soften the onion and carrots in oil, 6 minutes. Add garlic and cumin for 1 minute.", "Add the lentils and broth. Simmer 20 minutes.", "Blend half the soup and stir back in. Finish with lemon juice."],
     "Good with torn bread and olive oil."),
    ("sheet-pan-fajitas", "Sheet Pan Fajitas", ["Dinner", "Mexican", "Chicken"], "4", "15 min", "25 min", "Easy", "Notebook",
     ["1 lb chicken breast, sliced", "2 bell peppers, sliced", "1 red onion, sliced", "2 tbsp olive oil", "1 tbsp chili powder", "1 tsp cumin", "8 small flour tortillas", "2 limes"],
     ["Toss everything but the tortillas with oil and spices on a sheet pan.", "Roast at 425F for 22 minutes, stirring once.", "Warm tortillas. Serve with lime."],
     "Skirt steak works the same way."),
    ("blueberry-muffins", "Bakery-Style Blueberry Muffins", ["Breakfast", "Baking"], "12", "15 min", "22 min", "Easy", "Family recipe",
     ["2 cups flour", "3/4 cup sugar", "2 tsp baking powder", "1/2 tsp salt", "1/2 cup vegetable oil", "1 cup milk", "2 eggs", "1.5 cups blueberries", "2 tbsp coarse sugar"],
     ["Whisk the dry ingredients. Whisk the wet ingredients separately.", "Fold together until just combined, then fold in the berries.", "Fill a muffin tin to the top, sprinkle with coarse sugar. Bake at 425F for 5 minutes, then 350F for 17 minutes."],
     "The high start gives the domed tops."),
    ("shakshuka", "Shakshuka", ["Breakfast", "Vegetarian", "Middle Eastern"], "3", "10 min", "25 min", "Easy", "Friend recipe",
     ["2 tbsp olive oil", "1 onion, diced", "1 red pepper, diced", "3 cloves garlic", "1 tsp paprika", "1 tsp cumin", "1 can (28 oz) whole tomatoes", "6 eggs", "1/4 cup crumbled feta"],
     ["Soften the onion and pepper in oil. Add garlic and spices.", "Add the tomatoes, crush them, and simmer 12 minutes.", "Make six wells and crack in the eggs. Cover and cook 6 minutes. Top with feta."],
     "Serve with warm pita."),
    ("garlic-butter-shrimp", "Garlic Butter Shrimp Pasta", ["Dinner", "Pasta", "Seafood"], "4", "10 min", "15 min", "Easy", "Notebook",
     ["1 lb shrimp, peeled", "12 oz linguine", "4 tbsp butter", "5 cloves garlic, sliced", "1/2 tsp chili flakes", "1/2 cup dry white wine", "1 lemon", "2 tbsp chopped parsley"],
     ["Cook the pasta until al dente, reserving a cup of water.", "Sear the shrimp 90 seconds per side and set aside.", "Melt the butter, cook garlic and chili, add wine and reduce by half.", "Toss in pasta, shrimp, lemon juice and a splash of pasta water."],
     "Do not overcook the shrimp."),
    ("black-bean-tacos", "Crispy Black Bean Tacos", ["Dinner", "Mexican", "Vegetarian"], "4", "15 min", "20 min", "Easy", "Friend recipe",
     ["2 cans black beans, drained", "1 tsp cumin", "1 tsp smoked paprika", "8 corn tortillas", "1 cup shredded cheese", "1 avocado", "1/4 cup cilantro", "1 lime"],
     ["Mash the beans with the spices, leaving some whole.", "Fill tortillas with beans and cheese, fold, and pan-fry until crisp.", "Top with avocado, cilantro and lime."],
     ""),
    ("roast-chicken", "Simple Roast Chicken", ["Dinner", "Chicken"], "4", "10 min", "1 hr 15 min", "Easy", "Family recipe",
     ["1 whole chicken (4 lb)", "2 tbsp butter, softened", "1 tbsp kosher salt", "1 lemon", "1 head garlic", "fresh thyme"],
     ["Salt the chicken and leave uncovered in the fridge overnight if you can.", "Rub with butter, stuff with lemon, garlic and thyme.", "Roast at 425F for 70 minutes until the thigh reads 165F. Rest 15 minutes."],
     "Save the carcass for stock."),
    ("pad-see-ew", "Pad See Ew", ["Dinner", "Thai", "Noodles"], "2", "15 min", "10 min", "Medium", "Notebook",
     ["8 oz wide rice noodles", "2 tbsp dark soy sauce", "1 tbsp oyster sauce", "1 tsp sugar", "2 eggs", "2 cups Chinese broccoli, chopped", "3 cloves garlic", "2 tbsp neutral oil", "1/2 lb chicken thigh, sliced"],
     ["Soak noodles per the package. Mix the sauces and sugar.", "Sear the chicken in a very hot wok, then the garlic.", "Push aside, scramble the eggs, add the noodles, broccoli and sauce. Toss 2 minutes."],
     "A wok or cast iron gives the char."),
    ("banana-bread", "Brown Butter Banana Bread", ["Baking", "Breakfast"], "8", "15 min", "55 min", "Easy", "Family recipe",
     ["3 ripe bananas", "1/2 cup brown butter", "3/4 cup brown sugar", "1 egg", "1 tsp vanilla", "1 tsp baking soda", "1.5 cups flour", "1/2 tsp salt"],
     ["Brown the butter and cool slightly.", "Mash bananas, mix in butter, sugar, egg and vanilla.", "Fold in the dry ingredients. Bake at 350F for 55 minutes."],
     "Even better on day two."),
    ("chickpea-curry", "Coconut Chickpea Curry", ["Dinner", "Vegetarian", "Indian"], "4", "10 min", "25 min", "Easy", "Friend recipe",
     ["2 cans chickpeas", "1 can (13 oz) coconut milk", "1 onion", "3 cloves garlic", "1 tbsp curry powder", "1 can diced tomatoes", "3 cups spinach", "1 tbsp oil"],
     ["Soften the onion in oil. Add garlic and curry powder.", "Add tomatoes, chickpeas and coconut milk. Simmer 15 minutes.", "Wilt in the spinach. Serve with rice."],
     ""),
    ("caesar-salad", "Real Caesar Salad", ["Salad", "Side"], "4", "20 min", "", "Medium", "Notebook",
     ["2 heads romaine", "2 anchovy fillets", "1 clove garlic", "1 egg yolk", "1 tbsp lemon juice", "1/2 cup olive oil", "1/2 cup grated parmesan", "2 cups croutons"],
     ["Mash the anchovies and garlic to a paste. Whisk in yolk and lemon.", "Stream in the oil to emulsify.", "Toss with romaine, parmesan and croutons."],
     "Black pepper, lots of it."),
    ("pork-dumplings", "Pork and Cabbage Dumplings", ["Dinner", "Chinese", "Pork"], "6", "1 hr", "15 min", "Hard", "Family recipe",
     ["1 lb ground pork", "2 cups finely chopped napa cabbage", "2 scallions", "1 tbsp grated ginger", "1 tbsp soy sauce", "1 tbsp sesame oil", "40 dumpling wrappers"],
     ["Salt the cabbage, rest 10 minutes and squeeze dry.", "Mix with the pork and seasonings until sticky.", "Fill and pleat the wrappers.", "Pan-fry until golden, add a splash of water, cover and steam 6 minutes."],
     "Freeze uncooked on a tray before bagging."),
    ("french-onion-soup", "French Onion Soup", ["Soup", "French"], "4", "15 min", "1 hr 15 min", "Medium", "Notebook",
     ["4 large yellow onions, sliced", "3 tbsp butter", "1/2 cup dry sherry", "6 cups beef broth", "4 sprigs thyme", "4 slices baguette", "1 cup grated gruyere"],
     ["Cook the onions in butter over medium-low for 50 minutes until deep brown.", "Deglaze with sherry. Add broth and thyme and simmer 20 minutes.", "Top bowls with bread and cheese and broil until bubbling."],
     ""),
    ("pancakes", "Fluffy Buttermilk Pancakes", ["Breakfast", "Baking"], "4", "10 min", "15 min", "Easy", "Family recipe",
     ["2 cups flour", "2 tbsp sugar", "2 tsp baking powder", "1 tsp baking soda", "2 cups buttermilk", "2 eggs", "3 tbsp melted butter"],
     ["Whisk the dry ingredients. Whisk the buttermilk, eggs and butter.", "Combine gently; lumps are fine.", "Cook on a medium griddle until bubbles set, flip and finish."],
     "Rest the batter 5 minutes."),
    ("tomato-soup", "Roasted Tomato Soup", ["Soup", "Vegetarian"], "4", "10 min", "50 min", "Easy", "Notebook",
     ["2 lb ripe tomatoes, halved", "1 onion, quartered", "4 cloves garlic", "3 tbsp olive oil", "2 cups vegetable broth", "1/4 cup cream", "fresh basil"],
     ["Roast tomatoes, onion and garlic with oil at 425F for 40 minutes.", "Blend with the broth. Warm through with cream and basil."],
     "Grilled cheese is mandatory."),
    ("steak-frites", "Pan-Seared Steak With Herb Butter", ["Dinner", "Beef"], "2", "10 min", "15 min", "Medium", "Notebook",
     ["2 ribeye steaks", "1 tbsp kosher salt", "1 tbsp high-heat oil", "3 tbsp butter", "2 cloves garlic", "thyme", "parsley"],
     ["Salt the steaks and bring to room temperature.", "Sear in a ripping hot skillet 3 minutes per side.", "Add butter, garlic and thyme and baste 1 minute. Rest 8 minutes."],
     ""),
    ("peanut-noodles", "Cold Peanut Noodles", ["Dinner", "Noodles", "Vegetarian"], "4", "15 min", "10 min", "Easy", "Friend recipe",
     ["12 oz spaghetti", "1/3 cup peanut butter", "3 tbsp soy sauce", "2 tbsp rice vinegar", "1 tbsp chili crisp", "1 tbsp honey", "1 cucumber, julienned", "2 scallions"],
     ["Cook and rinse the noodles.", "Whisk the sauce with a little hot water until loose.", "Toss with noodles, cucumber and scallions."],
     "Great for a packed lunch."),
    ("lemon-bars", "Lemon Bars", ["Dessert", "Baking"], "16", "20 min", "40 min", "Easy", "Family recipe",
     ["1 cup butter", "2 cups flour", "1/2 cup powdered sugar", "4 eggs", "1.5 cups sugar", "3/4 cup lemon juice", "1/4 cup flour"],
     ["Press the crust (butter, 2 cups flour, powdered sugar) into a pan and bake at 350F for 20 minutes.", "Whisk the filling and pour over the warm crust.", "Bake 20 more minutes. Cool fully before dusting with sugar."],
     ""),
    ("chicken-congee", "Chicken Congee", ["Soup", "Chinese", "Breakfast"], "4", "10 min", "1 hr", "Easy", "Family recipe",
     ["1 cup jasmine rice", "8 cups chicken broth", "1 lb chicken thighs", "2 inch ginger, sliced", "scallions", "white pepper", "sesame oil"],
     ["Simmer the rice, broth, chicken and ginger for 50 minutes, stirring now and then.", "Shred the chicken back in. Top with scallions, pepper and sesame oil."],
     "Add a soft egg if you like."),
    ("cacio-e-pepe", "Cacio e Pepe", ["Dinner", "Italian", "Pasta"], "2", "5 min", "15 min", "Hard", "Notebook",
     ["8 oz spaghetti", "1 cup finely grated pecorino", "2 tsp black pepper, coarsely cracked", "1 tbsp butter"],
     ["Toast the pepper in a dry pan, add a ladle of pasta water.", "Add the pasta and butter, then off the heat, the cheese, tossing hard until creamy."],
     "The pan must come off the heat or the cheese clumps."),
    ("overnight-oats", "Overnight Oats", ["Breakfast", "Vegetarian"], "1", "5 min", "", "Easy", "Notebook",
     ["1/2 cup rolled oats", "1/2 cup milk", "1/4 cup yogurt", "1 tbsp chia seeds", "1 tsp maple syrup", "berries"],
     ["Stir everything but the berries in a jar.", "Refrigerate overnight and top with berries."],
     ""),
]


def seed(con, rnd, persona):
    pass  # no database; the notes are written by files()


def files(root, rnd, persona):
    d = root / "recipes"
    d.mkdir(parents=True, exist_ok=True)
    for i, (slug, title, cats, serv, prep, cook, diff, src, ing, steps, notes) in enumerate(R):
        fm = ["---", "type: recipe", f'title: "{title}"', "rating: 5", f'servings: "{serv}"', f'prep_time: "{prep}"']
        if cook:
            fm.append(f'cook_time: "{cook}"')
        fm += [f'difficulty: "{diff}"', "categories: [" + ", ".join(cats) + "]", f'source: "{src}"',
               "---", ""]
        body = ["## Ingredients", ""] + [f"- {x}" for x in ing] + ["", "## Directions", ""]
        body += [f"{n}. {s}" for n, s in enumerate(steps, 1)]
        if notes:
            body += ["", "## Notes", "", notes]
        (d / f"{slug}.md").write_text("\n".join(fm + body) + "\n", encoding="utf-8")

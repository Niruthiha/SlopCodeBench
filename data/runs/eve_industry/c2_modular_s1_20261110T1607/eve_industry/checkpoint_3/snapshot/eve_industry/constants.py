"""Static identifiers and file names used by the SDE."""

MANUFACTURING = 1
REACTIONS = 11
REVERSE_ENGINEERING = 7
INVENTION = 8
INVENTION_ACTIVITIES = (INVENTION, REVERSE_ENGINEERING)
PRODUCTION_ACTIVITIES = (MANUFACTURING, REACTIONS)

SHIP_CATEGORY_NAME = "Ship"
DEFAULT_TECH_LEVEL = "Tech I"
TECH_LEVELS = ("Tech III", "Tech II", "Tech I")  # longest suffix first

INV_TYPES = "invTypes.csv.bz2"
INV_GROUPS = "invGroups.csv.bz2"
INV_CATEGORIES = "invCategories.csv.bz2"
INV_MARKET_GROUPS = "invMarketGroups.csv.bz2"
INV_META_TYPES = "invMetaTypes.csv.bz2"
INV_META_GROUPS = "invMetaGroups.csv.bz2"
INDUSTRY_ACTIVITY = "industryActivity.csv.bz2"
INDUSTRY_PRODUCTS = "industryActivityProducts.csv.bz2"
INDUSTRY_MATERIALS = "industryActivityMaterials.csv.bz2"
INDUSTRY_PROBABILITIES = "industryActivityProbabilities.csv.bz2"
INDUSTRY_SKILLS = "industryActivitySkills.csv.bz2"
RAM_ACTIVITIES = "ramActivities.csv.bz2"
SHIP_VOLUMES = "ship_volumes.yaml"

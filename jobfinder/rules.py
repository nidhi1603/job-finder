"""Every filter rule in one editable place. All patterns are case-insensitive regexes."""
import re

I = re.IGNORECASE

MAX_AGE_DAYS = 15        # posted in the last 15 days
MAX_MIN_YOE = 2          # keep "0-3", "1-2", "1-3", "2+"; drop a stated minimum of 3 or more

# Title families to keep. A title must match one of these.
TITLE_FAMILIES = {
    "AI/ML": re.compile(
        r"\b(ai|a\.i\.|artificial intelligence|machine learning|ml|deep learning|nlp|natural language|llm|"
        r"gen(?:erative)?\s?ai|applied ai|computer vision)\b.*\b(engineer|developer|scientist)\b|\bmle\b", I),
    "Software": re.compile(r"\bsoftware (?:development )?(?:engineer|developer)\b|\bswe\b|\bback[- ]?end (?:software )?(?:engineer|developer)\b", I),
    "Data": re.compile(r"\bdata scien(?:tist|ce)\b|\bdata analyst\b", I),
    "Research": re.compile(r"\bresearch scientist\b|\bapplied scientist\b", I),
}

# Seniority in the title -> drop.
SENIOR_TITLE = re.compile(
    r"\b(senior|sr\.?|staff|principal|leads?|managers?|directors?|head of|vp|vice president|architects?|"
    r"distinguished|fellow|expert|mid[- ]?level|mid[- ]senior)\b|\b(ii|iii|iv|v)\b|\b(engineer|developer|scientist|analyst)\s*(2|3|4|5)\b|\bl[4-9]\b|\blevel\s*[2-9]\b", I)

INTERN_TITLE = re.compile(r"\bintern(ship)?\b|\bco-?op\b", I)

# US / non-US detection on location text.
US_STATES = ("Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|"
             "Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|"
             "Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|"
             "North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|"
             "South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming|"
             "District of Columbia")
US_ABBR = ("AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|"
           "NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC")
US_CITIES = (r"San Francisco|Bay Area|Silicon Valley|Palo Alto|Mountain View|Sunnyvale|San Jose|Menlo Park|Santa Clara|"
             r"Los Angeles|San Diego|Seattle|Bellevue|Redmond|Portland|New York|NYC|Brooklyn|Boston|Cambridge, MA|"
             r"Chicago|Austin|Dallas|Houston|Denver|Boulder|Atlanta|Miami|Philadelphia|Pittsburgh|Washington, D\.?C|"
             r"Arlington|Raleigh|Durham|Salt Lake City|Phoenix|Minneapolis|Detroit|Ann Arbor|Columbus|Nashville|"
             r"Charlotte|Baltimore|Irvine|Oakland|Berkeley|Princeton|Jersey City|Hoboken|Madison|St\.? Louis|Plano")
US_STRONG = re.compile(rf"\b(united states|u\.s\.a?\.?(?!\w)|usa)\b|\b({US_STATES})\b|\b({US_CITIES})\b", I)
US_TOKEN = re.compile(r"\bUS\b|\bUSA\b|\bU\.S\.")                       # case-sensitive
US_ABBR_STRICT = re.compile(rf"(?:,\s*|\bUS\W+)({US_ABBR})\b")           # case-sensitive ", CA"

# Titles that match a family but aren't the job she wants.
EXCLUDE_TITLE = re.compile(r"\b(sales|solutions?|support|customer|recruit\w*|marketing|account|pre-?sales|field)\b", I)
NON_US_LOCATION = re.compile(
    r"\b(canada|toronto|vancouver|montreal|ottawa|ontario|quebec|british columbia|alberta|calgary|edmonton|winnipeg|"
    r"manitoba|saskatchewan|nova scotia|halifax|new brunswick|newfoundland|mississauga|kitchener|waterloo, on|victoria, bc|united kingdom|uk|england|london|scotland|ireland|"
    r"dublin|germany|berlin|munich|france|paris|spain|madrid|barcelona|portugal|lisbon|netherlands|amsterdam|"
    r"belgium|switzerland|zurich|austria|vienna|poland|warsaw|krakow|czech|prague|romania|bucharest|hungary|"
    r"sweden|stockholm|norway|denmark|copenhagen|finland|italy|milan|rome|greece|israel|tel aviv|india|bangalore|"
    r"bengaluru|hyderabad|pune|mumbai|delhi|gurgaon|gurugram|noida|chennai|singapore|japan|tokyo|korea|seoul|"
    r"china|beijing|shanghai|shenzhen|hong kong|taiwan|taipei|hsinchu|vietnam|philippines|manila|indonesia|"
    r"malaysia|thailand|australia|sydney|melbourne|new zealand|mexico|brazil|são paulo|sao paulo|argentina|"
    r"buenos aires|colombia|bogota|chile|peru|costa rica|uruguay|south africa|nigeria|kenya|egypt|uae|dubai|"
    r"saudi|qatar|turkey|istanbul|ukraine|serbia|bulgaria|croatia|estonia|latvia|lithuania|emea|apac|latam|europe)\b", I)

CA_PROVINCE_ABBR = re.compile(r",\s*(BC|AB|ON|QC|MB|SK|NS|NB|NL|PE)\b")     # case-sensitive "Vancouver, BC"

# Drop: postings that ask the candidate to pay (training/placement/registration fees, deposits, bonds).
# Agencies themselves are fine; "we never charge a placement fee" is not a match (negations are checked in filters.py).
FEE_TERMS = re.compile(
    r"\b(?:training|placement|registration|enrol(?:l)?ment|marketing|processing|onboarding|certification|bench)\s+fees?\b|"
    r"\b(?:refundable|security)\s+deposit\b|\b(?:employment|service|training)\s+(?:agreement\s+)?bond\b|\bbond period\b|"
    r"\b(?:candidates?|you|trainees?|applicants?|consultants?)\s+(?:will\s+(?:be\s+)?|must\s+|need\s+to\s+|are\s+(?:required|expected)\s+to\s+|"
    r"have\s+to\s+)(?:pay|bear|cover)\s+(?:a|an|the|any|all|for)?\s*(?:one[- ]time\s+|upfront\s+|nominal\s+|small\s+)?"
    r"(?:fees?|deposit|costs? of (?:training|placement|marketing))", I)
FEE_NEGATION = re.compile(r"\b(?:no|never|not|without|free|zero|nor|don'?t|doesn'?t|do not|does not|won'?t|will not)\b[^.\n]{0,40}$", I)

# Flags (shown, not dropped): recruiting agencies posting for a client, training-and-placement programs.
AGENCY = re.compile(
    r"on behalf of (?:our|a|one of our) clients?|\bour client(?:s)? (?:is|are)\b|this role is for one of our clients|"
    r"(?:we are|we're) (?:a |an )?(?:staffing|recruiting|recruitment|talent) (?:agency|firm|company|partner)|"
    r"is recruiting for this (?:role|position)|\bfor (?:a|our) client\b", I)
TRAINING_PLACEMENT = re.compile(r"\btraining\s+(?:and|&)\s+placement\b|\bbench\s+(?:sales|marketing)\b", I)

# Drop: security clearance.
CLEARANCE = re.compile(
    r"security clearance|clearance (?:is )?required|(?:active|current|existing) (?:secret|ts|top secret|dod|government) "
    r"(?:security )?clearance|\bts/sci\b|top secret|secret clearance|(?:able|ability) to obtain (?:and maintain )?"
    r"(?:a |an )?(?:u\.?s\.? )?(?:government |security |secret )?clearance|public trust|polygraph", I)

# Drop: citizenship / green card / US person only.
CITIZENSHIP = re.compile(
    r"u\.?s\.? citizens? only|only (?:open to )?u\.?s\.? citizens|must (?:be|hold) (?:a )?u\.?s\.? citizen(?:ship)?|"
    r"u\.?s\.? citizenship (?:is )?(?:required|mandatory|a requirement)|requires? u\.?s\.? citizenship|"
    r"(?:green card|permanent resident)s? (?:holders? )?(?:only|required)|u\.?s\.? citizens? (?:or|and|/) (?:green card|"
    r"permanent resident|lawful permanent|u\.?s\.? national)|must be a u\.?s\.? person|u\.?s\.? persons? only|"
    r"\bitar\b|export[- ]control\w*.{0,100}(?:u\.?s\.? person|citizen)", I)

# Internships: drop if they need current enrollment, unless they also accept recent graduates.
ENROLLED = re.compile(
    r"currently (?:enrolled|pursuing|attending)|actively (?:enrolled|pursuing)|pursuing an? (?:bachelor|master|ph\.?d|"
    r"undergraduate|graduate|degree|b\.?s|m\.?s)|returning to (?:school|university|your studies)|rising (?:junior|senior)|"
    r"must be (?:a )?(?:current )?student|enrolled (?:full-time )?in an? (?:accredited )?(?:degree|university|college)|"
    r"expected graduation (?:date )?(?:in |between )?(?:fall |spring |winter |summer )?20(?:27|28|29)", I)
RECENT_GRAD = re.compile(
    r"recent(?:ly)? grad(?:uate|uated)?s?|graduated (?:with|within|in the (?:last|past))|new grad(?:uate)?s?|"
    r"recently (?:completed|received|earned)|early[- ]career|university grad(?:uate)?s?|graduat(?:e|ing) in 202[56]|"
    r"class of 202[56]", I)

# Boosts (rank higher) when the posting speaks to new grads.
BOOST = re.compile(
    r"new grad(?:uate)?s?|recent(?:ly)? grad(?:uate|uated)?s?|early[- ]career|university grad(?:uate)?s?|"
    r"entry[- ]level|graduate program|class of 202[56]|0\s*(?:-|–|to)\s*[1-3] years", I)

# Flags (shown, not dropped).
NO_SPONSOR = re.compile(
    r"(?:not|unable to|cannot|can't|won't|will not|do not|does not|don't) (?:be able to )?(?:currently )?"
    r"(?:provide|offer|support|consider)? ?(?:visa |immigration |h-?1b )?sponsor|no (?:visa |immigration )?sponsorship|"
    r"without (?:the need for |requiring )?(?:current or future |future )?(?:visa |employment |immigration )?sponsorship|"
    r"sponsorship (?:is |will )?not (?:be )?(?:available|provided|offered)", I)
SPONSORS = re.compile(r"(?:visa|h-?1b|immigration) sponsorship (?:is )?(?:available|provided|offered)|we (?:will |do )?sponsor", I)
DEGREE = [("PhD", re.compile(r"\bph\.?\s?d\.?\b|\bdoctora(?:te|l) degree\b", I)),
          ("MS", re.compile(r"\bmaster'?s?\b|\bm\.?s\.?\b(?= in|\b)", I)),
          ("BS", re.compile(r"\bbachelor'?s?\b|\bb\.?s\.?\b(?= in|\b)|\bundergraduate degree\b", I))]

# Section headings used to split "required" from "preferred".
PREFERRED_HDR = re.compile(r"\b(preferred|nice[- ]to[- ]have|bonus|pluses|a plus|desired|good to have|ideal(?:ly)?|extra credit)\b", I)
REQUIRED_HDR = re.compile(
    r"\b(requirements?|qualifications?|what you(?:'ll)? (?:need|bring)|must[- ]haves?|you have|you bring|who you are|"
    r"about you|what we(?:'re| are) looking for|skills|experience|you should have|basic|minimum)\b", I)

# Drop: PhD-only roles (a PhD is required and no master's/bachelor's/equivalent-experience route is offered).
PHD = re.compile(r"\bph\.?\s?d\.?\b|\bdoctora(?:te|l) degree\b", I)
NON_PHD_ROUTE = re.compile(
    r"\bmaster'?s?\b|\bm\.?s\.?(?=[\s,/)])|\bbachelor'?s?\b|\bb\.?s\.?(?=[\s,/)])|\bundergraduate\b|"
    r"equivalent (?:practical |industry |work |professional )?experience", I)
NOT_REQUIRED_WORDS = re.compile(r"prefer|a plus|is a plus|bonus|nice[- ]to[- ]have|desired|ideal", I)

#Find Blizzard employee's characters in World of Warcraft using Battle.net API

It is known that Blizzard employees receive Collector's Editions of Blizzard games as a job bonus. Most of them tend to activate codes for collector's editions in one day.

With above information in mind, I made a script that finds WoW characters that MAY belong to Blizzard employees.
It does so by looking for characters with Collector's Edition that is most rare nowadays - the one for original World of Warcraft.
It then saves character to a file. It also submits it to a website that aggregates results (read below about it).

To make viewing script results more convenient, I made a website: http://wow-gm-track.website/ It tries to hide false positives (and there are a lot of them!) by displaying characters that received at least 4 collector's editions in one day. It also shows additional information (such as total CE count, level, guild, twinks).

Not every character on the list on the website belongs to Blizzard employee. But the rule of thumb is: the more CE he obtained in one day, the more likely he is the one we are looking for. For example, if he obtained 6-7 and more CE in one day, he is likely (but not guaranteed, of course) to be Blizzard employee.

Usage:

>pip install -r requirements.txt

To scan randomly selected realm:

>python main.py

To scan specific realm:

>python main.py --realm=Outland

To scan specific region (default is EU):

>python main.py --region=us

To scan only for German realms, for example:

>python main.py --region=eu --locale=de_DE

Note: I am not associated with Blizzard Entertainment
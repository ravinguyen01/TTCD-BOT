"""Pure tests for public notices, emoji scores and point validation."""
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord
from classbot.attendance_notice import attendance_embeds, attendance_notices
from classbot.points import validate_points
from classbot.reaction import reaction_points


class NoticeTests(unittest.TestCase):
    def saved(self, rows, already=False):
        return {'code':'Mock Class', 'day':'2026-11-16', 'already':already, 'rows':rows}

    def test_counts_and_display_columns(self):
        rows=[{'present':False,'display_name':'Verified Name','discord_display_name':'Server Nick','discord_username':'username'},
              {'present':True,'display_name':'Present','discord_username':'present'},
              {'present':None,'display_name':'No Snapshot','discord_username':'excluded'}]
        embed=attendance_embeds(self.saved(rows))[0]
        self.assertIn('Sĩ số: 2 | Hiện diện: 1 | Vắng: 1',embed.description)
        self.assertEqual(embed.fields[0].value,'1. Verified Name')
        self.assertEqual(embed.fields[1].value,'1. Server Nick')
        self.assertNotIn('excluded','\n'.join(attendance_notices(self.saved(rows))))

    def test_fallback_and_empty_class(self):
        row={'present':False,'display_name':'','discord_display_name':'Display','discord_username':'username'}
        embed=attendance_embeds(self.saved([row]))[0]
        self.assertEqual(embed.fields[0].value,'1. Display')
        self.assertIn('Sĩ số: 0',attendance_embeds(self.saved([]))[0].description)

    def test_repeated_attendance_says_updated(self):
        self.assertIn('cập nhật',attendance_embeds(self.saved([],True))[0].description)

    def test_long_unicode_lists(self):
        rows=[{'present':False,'display_name':str(i)+'😀'*95,'discord_username':f'user{i}'} for i in range(120)]
        embeds=attendance_embeds(self.saved(rows))
        self.assertGreater(len(embeds),1)
        self.assertEqual(sum(len(e.fields[0].value.splitlines()) for e in embeds),120)
        for embed in embeds:
            self.assertEqual(len(embed.fields[0].value.splitlines()),len(embed.fields[1].value.splitlines()))
            self.assertTrue(all(len(f.value.encode('utf-16-le'))//2<=900 for f in embed.fields))
        self.assertTrue(all(len(s.encode('utf-16-le'))//2<=1800 for s in attendance_notices(self.saved(rows))))

    def test_all_skin_tones(self):
        for emoji,score in [('👍','0.1'),('🫰','0.2')]:
            for tone in ['']+[chr(c) for c in range(0x1f3fb,0x1f400)]:
                self.assertEqual(reaction_points(discord.PartialEmoji(name=emoji+tone)),Decimal(score))
        self.assertEqual(reaction_points(discord.PartialEmoji(name='⭐')),Decimal('0.5'))

    def test_custom_emoji_requires_correct_id(self):
        self.assertEqual(reaction_points(discord.PartialEmoji(name='1000',id=988685030916255815)),Decimal('1'))
        self.assertIsNone(reaction_points(discord.PartialEmoji(name='1000',id=123)))

    def test_signed_decimal_points(self):
        for value in ['-0.5','0.1','100','-100']:
            self.assertEqual(validate_points(value),Decimal(value))
        for value in ['0','100.01','0.001','NaN','Infinity']:
            with self.assertRaises(ValueError): validate_points(value)


if __name__=='__main__':
    unittest.main()

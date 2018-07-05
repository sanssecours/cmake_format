from __future__ import print_function
from __future__ import unicode_literals

import re
import sys

from cmake_format import common

# NOTE(josh): inspiration and some bits taken from cmakeast_ and
# cmakelistparsing_
#
# .. _cmake_ast: https://github.com/polysquare/cmake-ast
# .. _cmakelist_parsing: https://github.com/ijt/cmakelists_parsing


class TokenType(common.EnumObject):
  _id_map = {}


TokenType.QUOTED_LITERAL = TokenType(0)
TokenType.LEFT_PAREN = TokenType(1)
TokenType.RIGHT_PAREN = TokenType(2)
TokenType.WORD = TokenType(3)
TokenType.NUMBER = TokenType(4)
TokenType.DEREF = TokenType(5)
TokenType.WHITESPACE = TokenType(6)
TokenType.NEWLINE = TokenType(7)
TokenType.COMMENT = TokenType(8)
TokenType.UNQUOTED_LITERAL = TokenType(9)
TokenType.FORMAT_OFF = TokenType(10)
TokenType.FORMAT_ON = TokenType(11)
TokenType.BRACKET_ARGUMENT = TokenType(12)
TokenType.BRACKET_COMMENT = TokenType(13)


class SourceLocation(tuple):
  """
  Named tuple of (line, col, offset)
  """

  # def __init__(self, line, col, offset):
  #   super(SourceLocation, self).__init__((line, col, offset))

  @property
  def line(self):
    return self[0]

  @property
  def col(self):
    return self[1]

  @property
  def offset(self):
    return self[2]

  def __repr__(self):
    return '{}:{}'.format(self.line, self.col)


class Token(object):
  """
  Lexical unit of a listfile.
  """

  def __init__(self, tok_type, spelling, index, begin, end):
    self.type = tok_type
    self.spelling = spelling
    self.index = index
    self.begin = begin
    self.end = end

  @property
  def content(self):
    return self.spelling

  # TODO(josh): get rid of this? Is it used or did I accidentally add it when
  # I meant to add get_location()?
  def location(self):
    return self.begin

  def get_location(self):
    return self.begin

  def count_newlines(self):
    return self.spelling.count('\n')

  def __repr__(self):
    """A string representation of this token."""
    return ("Token(type={0}, "
            "content={1}, "
            "line={2}, "
            "col={3})").format(self.type.name, repr(self.spelling), *self.begin)


def tokenize(contents):
  """
  Scan a string and return a list of Token objects representing the contents
  of the cmake listfile.
  """
  # Regexes are in priority order. Changing the order may alter the
  # behavior of the lexer
  scanner = re.Scanner([
      # double quoted string
      # NOTE(josh): regex borrowed from
      # https://stackoverflow.com/a/37379449/141023
      (r'(?<![^\s\(])"[^"\\]*(?:\\.[^"\\]*)*"(?![^\s\)])',
       lambda s, t: (TokenType.QUOTED_LITERAL, t)),
      # single quoted string
      (r"(?<![^\s\(])'[^'\\]*(?:\\.[^'\\]*)*'(?![^\s\)])",
       lambda s, t: (TokenType.QUOTED_LITERAL, t)),
      # bracket argument
      (r"(?<![^\s\(])\[(=*)\[.*\]\1\](?![^\s\)])",
       lambda s, t: (TokenType.BRACKET_ARGUMENT, t)),
      (r"(?<![^\s\(])-?[0-9]+(?![^\s\)\(])",
       lambda s, t: (TokenType.NUMBER, t)),
      (r"\(", lambda s, t: (TokenType.LEFT_PAREN, t)),
      (r"\)", lambda s, t: (TokenType.RIGHT_PAREN, t)),
      # Either a valid function name or variable name.
      (r"(?<![^\s\(])[a-zA-z_][a-zA-Z0-9_]*(?![^\s\)\(])",
       lambda s, t: (TokenType.WORD, t)),
      # Variable dereference. Borrowed from cmakeast.
      # NOTE(josh): I don't think works for nested derefs.
      (r"(?<![^\s\(])\${[a-zA-z_][a-zA-Z0-9_]*}(?![^\s\)])",
       lambda s, t: (TokenType.DEREF, t)),
      # NOTE(josh): bare carriage returns are very unlikely to be used but
      # just for the case of explicitnes, if we ever encounter any we treat
      # it as a newline
      (r"\r?\n", lambda s, t: (TokenType.NEWLINE, t)),
      (r"\r\n?", lambda s, t: (TokenType.NEWLINE, t)),
      # NOTE(josh): don't match '\s' here or we'll miss some newline tokens
      # TODO(josh): should we match unicode whitespace too?
      (r"[ \t\f\v]+", lambda s, t: (TokenType.WHITESPACE, t)),
      (r"#\s*cmake-format: off[^\n]*", lambda s, t: (TokenType.FORMAT_OFF, t)),
      (r"#\s*cmake-format: on[^\n]*", lambda s, t: (TokenType.FORMAT_ON, t)),
      # bracket comment
      (r"#\[(=*)\[.*\]\1\]", lambda s, t: (TokenType.BRACKET_COMMENT, t)),
      # line comment
      (r"#[^\n]*", lambda s, t: (TokenType.COMMENT, t)),
      # Catch-all for literals which are compound statements.
      (r"([^\s\(\)]+|[^\s\(]*[^\)]|[^\(][^\s\)]*)",
       lambda s, t: (TokenType.UNQUOTED_LITERAL, t))
  ], re.DOTALL)

  tokens, remainder = scanner.scan(contents)
  assert not remainder, "Unparsed tokens: {}".format(remainder)

  # Now add line, column, and serial number to token objects. We get lineno
  # by maintaining a running count of newline characters encountered among
  # tokens so far, and column count by splitting the most recent token on
  # it's right most newline. Note that line and numbers are 1-indexed to match
  # up with editors but column numbers are zero indexed because its fun to be
  # inconsistent.
  tokens_return = []
  lineno = 1
  col = 0
  offset = 0
  for tok_index, (tok_type, spelling) in enumerate(tokens):
    if sys.version_info[0] < 3:
      assert isinstance(spelling, unicode)
    begin = SourceLocation((lineno, col, offset))

    newlines = spelling.count('\n')
    lineno += newlines
    if newlines:
      col = len(spelling.rsplit('\n', 1)[1])
    else:
      col += len(spelling)

    offset += len(bytearray(spelling, 'utf-8'))
    tokens_return.append(Token(tok_type=tok_type,
                               spelling=spelling,
                               index=tok_index,
                               begin=begin,
                               end=SourceLocation((lineno, col, offset))))

  return tokens_return


def parse_bracket_argument(text):
  regex = re.compile(r'^\[(=*)\[(.*)\]\1\]$', re.DOTALL)
  match = regex.match(text)
  assert match, "Failed to match bracket argument pattern in {}".format(text)
  return ('[' + match.group(1) + '[',
          match.group(2),
          ']' + match.group(1) + ']')


def parse_bracket_comment(text):
  prefix, content, suffix = parse_bracket_argument(text[1:])
  return ('#' + prefix, content, suffix)


def main():
  """
  Dump tokenized listfile to stdout for debugging.
  """
  import argparse
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('infile')
  args = parser.parse_args()
  with open(args.infile, 'r') as infile:
    tokens = tokenize(infile.read())
  print('\n'.join(str(x) for x in tokens))


if __name__ == '__main__':
  main()

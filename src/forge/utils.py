def merge_dicts(dict1, dict2):
  """
  Merges two multi-level dictionaries recursively.

  Args:
      dict1: The first dictionary.
      dict2: The second dictionary.

  Returns:
      A new dictionary with the merged values from dict1 and dict2.
  """

  merged = dict1.copy()
  for key, value in dict2.items():
    if key in merged:
      if isinstance(value, dict) and isinstance(merged[key], dict):
        merged[key] = merge_dicts(merged[key], value)
      else:
        merged[key] = value
    else:
      merged[key] = value
  return merged
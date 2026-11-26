import { Checkbox, type CheckboxProps, Stack } from "@mantine/core";

/**
 * The two consents required by Kazakhstan's personal data law: processing, and transfer abroad (art. 16),
 * e.g. to editors and reviewers in other countries, the e-mail provider and Crossref.
 */
export function ConsentFields({
  privacy,
  crossBorder,
}: {
  privacy: CheckboxProps;
  crossBorder: CheckboxProps;
}) {
  return (
    <Stack gap="xs">
      <Checkbox
        {...privacy}
        label="I agree to the processing of my personal data according to the journal's privacy policy."
      />
      <Checkbox
        {...crossBorder}
        label="I agree that my personal data may be transferred outside Kazakhstan when needed to handle manuscripts: to editors and reviewers abroad, the e-mail provider, DOI registration (Crossref) and similarity checking."
      />
    </Stack>
  );
}

#ifndef AIOS_SHELL_SHELL_H_
#define AIOS_SHELL_SHELL_H_

#ifndef PROMPT_STYLE
#define PROMPT_STYLE 1
#endif

void shell_run(void);
void shell_prompt(void);
void shell_process_line(const char *line);

#endif  /* AIOS_SHELL_SHELL_H_ */

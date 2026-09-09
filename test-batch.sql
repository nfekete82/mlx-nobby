INSERT INTO users (id, name, email, active)
VALUES (1, 'Max Mustermann', 'max@example.de', 0);

INSERT INTO users (id, name, email, active)
VALUES (2, 'Anna Beispiel', 'anna@example.de', 0);

UPDATE users
SET active = 0
WHERE id = 1;
